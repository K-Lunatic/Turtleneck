use html5ever::tendril::StrTendril;
use html5ever::tokenizer::{states::RawKind, BufferQueue, Tag, TagKind, Token, TokenSink, TokenSinkResult, Tokenizer};
use serde::Serialize;
use std::{cell::RefCell, rc::Rc};
use crate::{normalized, whitespace};

#[derive(Serialize)]
pub struct Overview {
    id: String,
    name: String,
    text: String,
}

#[derive(Default)]
struct State {
    items: Vec<Overview>,
    section: Option<Overview>,
    li_stack: Vec<(bool, bool)>,
    tags: Vec<(String, bool)>,
    hidden_depth: usize,
    activity_depth: usize,
    unsupported: bool,
}

fn attr<'a>(tag: &'a Tag, name: &str) -> &'a str {
    tag.attrs.iter().find(|value| &*value.name.local == name).map(|value| value.value.as_ref()).unwrap_or("")
}

impl State {
    fn start(&mut self, tag: &Tag) {
        let name: &str = tag.name.as_ref();
        let classes: Vec<_> = attr(tag, "class").split(whitespace).collect();
        if name == "li" {
            let section = classes.contains(&"section") && self.section.is_none();
            let activity = classes.contains(&"activity") && self.section.is_some();
            self.li_stack.push((section, activity));
            if section {
                self.section = Some(Overview { id: attr(tag, "id").to_owned(), name: attr(tag, "aria-label").to_owned(), text: String::new() });
            }
            if activity { self.activity_depth += 1; }
        }
        let style = attr(tag, "style").replace(' ', "").to_lowercase();
        let hidden = tag.attrs.iter().any(|value| &*value.name.local == "hidden")
            || attr(tag, "aria-hidden") == "true"
            || classes.iter().any(|value| matches!(*value, "hidden" | "d-none" | "accesshide" | "sr-only"))
            || style.contains("display:none") || style.contains("visibility:hidden")
            || matches!(name, "script" | "style" | "noscript" | "template");
        if !matches!(name, "area" | "base" | "br" | "col" | "embed" | "hr" | "img" | "input" | "link" | "meta" | "param" | "source" | "track" | "wbr") {
            self.tags.push((name.to_owned(), hidden));
            if hidden { self.hidden_depth += 1; }
        }
    }

    fn end(&mut self, name: &str) {
        if let Some(index) = self.tags.iter().rposition(|value| value.0 == name) {
            self.hidden_depth -= self.tags[index..].iter().filter(|value| value.1).count();
            self.tags.truncate(index);
        }
        if name != "li" { return; }
        let Some((section, activity)) = self.li_stack.pop() else { return; };
        if activity { self.activity_depth -= 1; }
        if section {
            if let Some(mut value) = self.section.take() {
                value.name = normalized(&value.name);
                value.text = normalized(&value.text);
                if !value.name.is_empty() {
                    if let Some(rest) = value.text.strip_prefix(&value.name) {
                        value.text = rest.trim_matches([' ', ':', '·', '-', '—']).to_owned();
                    }
                }
                if value.text.chars().count() >= 12 {
                    if value.name.is_empty() { value.name = "강의 개요".to_owned(); }
                    self.items.push(value);
                }
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
                let name: &str = tag.name.as_ref();
                if tag.kind == TagKind::StartTag {
                    state.start(&tag);
                    if tag.self_closing { state.end(name); }
                    else if name == "script" { return TokenSinkResult::RawData(RawKind::ScriptData); }
                    else if name == "style" { return TokenSinkResult::RawData(RawKind::Rawtext); }
                } else { state.end(name); }
            }
            Token::CharacterTokens(text) => {
                if state.hidden_depth == 0 && state.activity_depth == 0 {
                    if let Some(section) = &mut state.section { section.text.push_str(&text); }
                }
            }
            Token::ParseError(_) | Token::NullCharacterToken => state.unsupported = true,
            _ => {}
        }
        TokenSinkResult::Continue
    }
}

pub fn parse(html: &str) -> Result<Vec<Overview>, ()> {
    let state = Rc::new(RefCell::new(State::default()));
    let tokenizer = Tokenizer::new(Sink(state.clone()), Default::default());
    let input = BufferQueue::default();
    input.push_back(StrTendril::from_slice(html));
    let _ = tokenizer.feed(&input);
    tokenizer.end();
    let mut state = state.borrow_mut();
    if state.unsupported { Err(()) } else { Ok(std::mem::take(&mut state.items)) }
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn excludes_hidden_and_activity_content() {
        let rows = parse("<li class='section' id='s' aria-label='개요'>개요 : 열두 글자 이상의 수업 설명입니다.<span hidden>비공개</span><li class='activity'>자료 설명</li></li>").unwrap();
        assert_eq!(rows.len(), 1);
        assert_eq!(rows[0].text, "열두 글자 이상의 수업 설명입니다.");
    }
    #[test]
    fn length_is_in_unicode_characters() {
        assert!(parse("<li class='section'>짧은 한글</li>").unwrap().is_empty());
    }
}
