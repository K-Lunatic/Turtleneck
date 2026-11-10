"""Small dependency-free document export for assignment drafts."""
from __future__ import annotations

from html import escape
import shutil
import subprocess
import tempfile
from pathlib import Path
import zipfile


def _paragraphs(markdown: str) -> list[str]:
    result = []
    for line in str(markdown or '').splitlines():
        line = line.strip()
        if not line:
            continue
        while line[:1] in '#*-':
            line = line[1:].lstrip()
        result.append(line)
    return result or ['']


def _write_docx(markdown: str, output: Path) -> None:
    body = ''.join(
        f'<w:p><w:r><w:t xml:space="preserve">{escape(line)}</w:t></w:r></w:p>'
        for line in _paragraphs(markdown)
    )
    document = f'''<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:body>{body}
<w:sectPr><w:pgSz w:w="11906" w:h="16838"/><w:pgMar w:top="1440" w:right="1440" w:bottom="1440" w:left="1440"/></w:sectPr></w:body></w:document>'''
    output.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(output, 'w', zipfile.ZIP_DEFLATED) as archive:
        archive.writestr('[Content_Types].xml', '''<?xml version="1.0" encoding="UTF-8"?>
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>
<Default Extension="xml" ContentType="application/xml"/>
<Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>
</Types>''')
        archive.writestr('_rels/.rels', '''<?xml version="1.0" encoding="UTF-8"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/>
</Relationships>''')
        archive.writestr('word/document.xml', document)


def write_document(markdown: str, output: str | Path, *, overwrite: bool = False) -> Path:
    target = Path(output).expanduser().resolve()
    if target.exists() and not overwrite:
        raise ValueError('같은 이름의 결과 파일이 있어 덮어쓰지 않았어요.')
    extension = target.suffix.casefold()
    if extension == '.md':
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(markdown, encoding='utf-8')
        return target
    if extension == '.docx':
        _write_docx(markdown, target)
        return target
    if extension == '.hwpx':
        soffice = shutil.which('soffice') or shutil.which('libreoffice')
        if not soffice:
            raise ValueError('HWPX 쓰기에는 LibreOffice가 필요해요. Markdown 또는 DOCX로는 바로 저장할 수 있어요.')
        with tempfile.TemporaryDirectory(prefix='turtleneck-doc-') as folder:
            source = Path(folder) / 'turtleneck-draft.docx'
            _write_docx(markdown, source)
            result = subprocess.run([soffice, '--headless', '--convert-to', 'hwpx', '--outdir', folder, str(source)],
                                    capture_output=True, text=True, timeout=120)
            converted = Path(folder) / 'turtleneck-draft.hwpx'
            if result.returncode != 0 or not converted.is_file():
                raise ValueError('LibreOffice가 HWPX로 변환하지 못했어요. DOCX 결과를 사용해 주세요.')
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(converted, target)
        return target
    if extension == '.hwp':
        raise ValueError('구형 HWP 바이너리 쓰기는 지원하지 않아요. HWPX·DOCX·Markdown으로 저장해 주세요.')
    raise ValueError('지원하는 결과 형식은 Markdown, DOCX, HWPX입니다.')
