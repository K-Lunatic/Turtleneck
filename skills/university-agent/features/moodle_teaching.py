"""Small, response-driven helpers for Moodle instructor workflows."""
from __future__ import annotations

from html import unescape
from html.parser import HTMLParser
from pathlib import Path
import re
from urllib.parse import unquote, urljoin, urlsplit


class _VisibleLinks(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.links: list[dict[str, str]] = []
        self._hidden_tags: list[str] = []
        self.anchor: dict[str, object] | None = None

    def handle_starttag(self, tag, attrs):
        values = dict(attrs)
        classes = (values.get('class') or '').split()
        is_hidden = (tag in {'script', 'style', 'noscript', 'template'} or
                     'hidden' in values or values.get('aria-hidden') == 'true' or
                     any(item in classes for item in ('hidden', 'd-none', 'accesshide', 'sr-only')) or
                     re.search(r'display\s*:\s*none|visibility\s*:\s*hidden', values.get('style') or '', re.I))
        if tag == 'a' and not self._hidden_tags and values.get('href'):
            self.anchor = {'href': values['href'], 'text': []}
        if is_hidden:
            self._hidden_tags.append(tag)

    def handle_endtag(self, tag):
        if tag == 'a' and self.anchor is not None:
            self.links.append({'href': str(self.anchor['href']),
                               'text': ' '.join(''.join(self.anchor['text']).split())})
            self.anchor = None
        if self._hidden_tags and self._hidden_tags[-1] == tag:
            self._hidden_tags.pop()

    def handle_data(self, data):
        if self.anchor is not None and not self._hidden_tags:
            self.anchor['text'].append(data)


def _origin(base_url: str):
    parts = urlsplit(base_url)
    return parts.scheme, parts.hostname, parts.port or (443 if parts.scheme == 'https' else 80)


def _same_origin(url: str, base_url: str) -> bool:
    try:
        parts = urlsplit(url)
        return (parts.scheme, parts.hostname, parts.port or (443 if parts.scheme == 'https' else 80)) == _origin(base_url)
    except ValueError:
        return False


def _links(html: str, base_url: str) -> list[dict[str, str]]:
    parser = _VisibleLinks()
    parser.feed(html)
    result = []
    for item in parser.links:
        url = urljoin(base_url.rstrip('/') + '/', unescape(item['href']))
        if _same_origin(url, base_url):
            result.append({**item, 'url': url})
    return result


def inspect_teacher_capabilities(html: str, base_url: str) -> dict[str, object]:
    """Infer only capabilities proven by visible, same-site management links."""
    evidence = []
    has_grading = False
    has_editing = False
    for item in _links(html, base_url):
        parts = urlsplit(item['url'])
        path = parts.path
        text = item['text'].casefold()
        if path in {'/course/modedit.php', '/course/edit.php'} or 'edit=on' in parts.query:
            has_editing = True
            evidence.append(path)
        if '/mod/assign/' in path and ('grading' in parts.query or 'grading' in path or
                                      re.search(r'채점|성적|grade|submission', text, re.I)):
            has_grading = True
            evidence.append(path)
        if path in {'/files/edit.php', '/repository/repository_ajax.php'} or re.search(r'자료.*추가|upload|파일.*추가', text, re.I):
            has_editing = True
            evidence.append(path)
    capabilities = {
        'bulkGrading': has_grading,
        'submissionDownload': has_grading,
        'materialUpload': has_editing,
        'courseEditing': has_editing,
    }
    return {
        'role': 'teacher_or_manager' if any(capabilities.values()) else 'student_or_unknown',
        'capabilities': capabilities,
        'evidence': sorted(set(evidence)),
        'verifiedBy': 'visible_same_origin_links',
    }


def observed_submission_files(html: str, base_url: str) -> list[dict[str, str]]:
    """Return visible Moodle file links; no student or file URL is guessed."""
    result = []
    seen = set()
    for item in _links(html, base_url):
        url, path = item['url'], urlsplit(item['url']).path
        if not (path.startswith('/pluginfile.php/') or
                (path.startswith('/mod/assign/') and 'download' in path)):
            continue
        if url in seen:
            continue
        seen.add(url)
        name = unquote(Path(path).name) or 'submission'
        result.append({'url': url, 'label': item['text'], 'filename': name})
    return result


def _safe_filename(value: str) -> str:
    value = re.sub(r'[\\/:*?"<>|\x00-\x1f]+', '_', str(value)).strip(' .')
    if not value or value in {'.', '..'}:
        raise ValueError('제출물 파일명이 비어 있거나 안전하지 않아요.')
    return value[:180]


def submission_plan(files: list[dict[str, str]], *, course: str = '', assignment: str = '', template: str = '{index:03d}_{filename}') -> list[dict[str, str]]:
    planned = []
    names = set()
    for index, item in enumerate(files, 1):
        try:
            name = template.format(index=index, course=course, assignment=assignment,
                                  label=item.get('label', ''), filename=item.get('filename', 'submission'))
        except (KeyError, ValueError, IndexError) as error:
            raise ValueError('파일명 양식에는 index, course, assignment, label, filename만 사용할 수 있어요.') from error
        name = _safe_filename(name)
        if name in names:
            raise ValueError(f'같은 이름으로 저장되는 제출물이 있어요: {name}')
        names.add(name)
        planned.append({'source': item['url'], 'label': item.get('label', ''), 'filename': name})
    return planned


def save_submission_bytes(root: Path, name: str, content: bytes, *, overwrite: bool = False) -> Path:
    root = root.expanduser().resolve()
    root.mkdir(parents=True, exist_ok=True)
    target = (root / _safe_filename(name)).resolve()
    if target.parent != root:
        raise ValueError('제출물 파일명이 저장 폴더 밖을 가리켜요.')
    if target.exists() and not overwrite:
        raise FileExistsError(f'같은 이름의 파일이 이미 있어요: {target.name}')
    temporary = target.with_name(f'.{target.name}.part')
    temporary.write_bytes(content)
    temporary.replace(target)
    return target


def inspect_grading_form(html: str, base_url: str) -> dict[str, object]:
    """Describe observed grade inputs without exposing names or submitting anything."""
    for form in re.finditer(r'<form\b[^>]*action=["\']([^"\']*)["\'][^>]*>(.*?)</form>', html, re.I | re.S):
        fields = sorted(set(re.findall(r'name=["\']grade\[([1-9][0-9]*)\]["\']', form.group(2), re.I)))
        action = urljoin(base_url.rstrip('/') + '/', unescape(form.group(1)))
        if fields and _same_origin(action, base_url):
            return {'available': True, 'studentCount': len(fields), 'gradeFieldCount': len(fields),
                    'formAction': urlsplit(action).path, 'reason': None}
    return {'available': False, 'studentCount': 0, 'gradeFieldCount': 0,
            'formAction': None, 'reason': '실제 채점 양식과 학생별 점수 입력칸을 확인하지 못했어요.'}
