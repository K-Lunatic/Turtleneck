use html5ever::tendril::StrTendril;
use html5ever::tokenizer::{BufferQueue, Tag, TagKind, Token, TokenSink, TokenSinkResult, Tokenizer};
use html5ever::tokenizer::states::RawKind;
use serde::Serialize;
use std::{cell::RefCell, panic::catch_unwind, ptr, rc::Rc};

const MAX_INPUT: usize = 32 * 1024 * 1024;
mod overview;
mod concept;

#[derive(Default, Serialize)]
struct Activity {
    href: String,
    title: String,
    text: String,
    #[serde(rename = "type")]
    kind: String,
}

#[derive(Default)]
struct State {
    items: Vec<Activity>,
    current: Option<Activity>,
    li_depth: usize,
    anchor: String,
    in_anchor: bool,
    unsupported: bool,
}

fn whitespace(ch: char) -> bool {
    ch.is_whitespace() || ('\u{001c}'..='\u{001f}').contains(&ch)
}

fn normalized(text: &str) -> String {
    text.split(whitespace).filter(|part| !part.is_empty()).collect::<Vec<_>>().join(" ")
}

impl State {
    fn start(&mut self, tag: &Tag) {
        if &*tag.name == "li" {
            if self.current.is_none() {
                let classes = tag.attrs.iter().find(|attr| &*attr.name.local == "class")
                    .map(|attr| attr.value.as_ref()).unwrap_or("");
                if classes.split(whitespace).any(|class| class == "activity") {
                    let kind = classes.split(whitespace).find_map(|class| class.strip_prefix("modtype_"))
                        .unwrap_or("").to_owned();
                    self.current = Some(Activity { kind, ..Activity::default() });
                    self.li_depth = 1;
                }
            } else {
                self.li_depth += 1;
            }
        }
        if &*tag.name == "a" {
            if let Some(current) = &mut self.current {
                if current.href.is_empty() {
                    current.href = tag.attrs.iter().find(|attr| &*attr.name.local == "href")
                        .map(|attr| attr.value.to_string()).unwrap_or_default();
                    self.anchor.clear();
                    self.in_anchor = true;
                }
            }
        }
    }

    fn end(&mut self, tag: &str) {
        if tag == "a" && self.in_anchor {
            if let Some(current) = &mut self.current {
                current.title = normalized(&self.anchor);
                self.anchor.clear();
                self.in_anchor = false;
            }
        }
        if tag == "li" && self.current.is_some() {
            self.li_depth -= 1;
            if self.li_depth == 0 {
                let mut current = self.current.take().unwrap();
                current.text = normalized(&current.text);
                self.items.push(current);
            }
        }
    }
}

struct Sink(Rc<RefCell<State>>);

impl TokenSink for Sink {
    type Handle = ();

    fn process_token(&self, token: Token, _: u64) -> TokenSinkResult<()> {
        let mut state = self.0.borrow_mut();
        match token {
            Token::TagToken(tag) => {
                let name = tag.name.as_ref();
                if tag.kind == TagKind::StartTag {
                    state.start(&tag);
                    if tag.self_closing {
                        state.end(name);
                    } else if name == "script" {
                        return TokenSinkResult::RawData(RawKind::ScriptData);
                    } else if name == "style" {
                        return TokenSinkResult::RawData(RawKind::Rawtext);
                    }
                } else {
                    state.end(name);
                }
            }
            Token::CharacterTokens(text) => {
                if let Some(current) = &mut state.current {
                    current.text.push_str(&text);
                    if state.in_anchor {
                        state.anchor.push_str(&text);
                    }
                }
            }
            // Python HTMLParser has different recovery rules; never silently change its output.
            Token::ParseError(_) | Token::NullCharacterToken => state.unsupported = true,
            _ => {}
        }
        TokenSinkResult::Continue
    }
}

fn parse(html: &str) -> Result<Vec<Activity>, ()> {
    let state = Rc::new(RefCell::new(State::default()));
    let tokenizer = Tokenizer::new(Sink(state.clone()), Default::default());
    let input = BufferQueue::default();
    input.push_back(StrTendril::from_slice(html));
    let _ = tokenizer.feed(&input);
    tokenizer.end();
    let mut state = state.borrow_mut();
    if state.unsupported { Err(()) } else { Ok(std::mem::take(&mut state.items)) }
}

#[repr(C)]
pub struct Buffer {
    pub data: *mut u8,
    pub len: usize,
    pub capacity: usize,
    pub status: u32,
}

fn failure(status: u32) -> Buffer {
    Buffer { data: ptr::null_mut(), len: 0, capacity: 0, status }
}

/// Input must point to `len` readable bytes for the duration of this call.
#[unsafe(no_mangle)]
pub unsafe extern "C" fn activity_parse(data: *const u8, len: usize) -> Buffer {
    unsafe { export_parse(data, len, parse) }
}

/// Input must point to `len` readable bytes for the duration of this call.
#[unsafe(no_mangle)]
pub unsafe extern "C" fn overview_parse(data: *const u8, len: usize) -> Buffer {
    unsafe { export_parse(data, len, overview::parse) }
}

/// Input must point to a UTF-8 JSON payload of `len` readable bytes.
#[unsafe(no_mangle)]
pub unsafe extern "C" fn concept_rank(data: *const u8, len: usize) -> Buffer {
    unsafe { export_parse(data, len, concept::rank) }
}

unsafe fn export_parse<T: Serialize>(data: *const u8, len: usize, parser: fn(&str) -> Result<T, ()>) -> Buffer {
    if len > MAX_INPUT || (data.is_null() && len != 0) { return failure(1); }
    let result = catch_unwind(|| {
        let input = if len == 0 { &[] } else { unsafe { std::slice::from_raw_parts(data, len) } };
        let html = std::str::from_utf8(input).map_err(|_| 1_u32)?;
        let items = parser(html).map_err(|_| 2_u32)?;
        serde_json::to_vec(&items).map_err(|_| 3_u32)
    });
    match result {
        Ok(Ok(mut bytes)) => {
            let result = Buffer { data: bytes.as_mut_ptr(), len: bytes.len(), capacity: bytes.capacity(), status: 0 };
            std::mem::forget(bytes);
            result
        }
        Ok(Err(status)) => failure(status),
        Err(_) => failure(3),
    }
}

/// Accepts only a buffer returned once by `activity_parse`, never an arbitrary pointer.
#[unsafe(no_mangle)]
pub unsafe extern "C" fn activity_free(buffer: Buffer) {
    if !buffer.data.is_null() {
        drop(unsafe { Vec::from_raw_parts(buffer.data, buffer.len, buffer.capacity) });
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn extracts_nested_activity_text_and_entities() {
        let parsed = parse("<li class='activity modtype_resource'><a href='/file?a=1&amp;b=2'>자료 &amp; 예제</a><ul><li>다운로드 금지</li></ul></li>").unwrap();
        assert_eq!(parsed.len(), 1);
        assert_eq!(parsed[0].href, "/file?a=1&b=2");
        assert_eq!(parsed[0].title, "자료 & 예제");
        assert_eq!(parsed[0].text, "자료 & 예제다운로드 금지");
        assert_eq!(parsed[0].kind, "resource");
    }

    #[test]
    fn duplicate_attributes_require_python_recovery() {
        assert!(parse("<li class='activity' class='other'>text</li>").is_err());
    }

    #[test]
    fn validates_ffi_input_and_frees_owned_output() {
        assert_eq!(unsafe { activity_parse(ptr::null(), 1) }.status, 1);
        let output = unsafe { activity_parse(ptr::null(), 0) };
        assert_eq!(output.status, 0);
        assert_eq!(unsafe { std::slice::from_raw_parts(output.data, output.len) }, b"[]");
        unsafe { activity_free(output) };
    }
}
