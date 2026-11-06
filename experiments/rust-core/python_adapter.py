"""Experimental one-process Rust activity parser; production stays on Python."""
import ctypes
import json
from pathlib import Path
import re
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'skills/university-agent'))
from providers.moodle_provider import _ActivityParser as PythonActivityParser

CR_IN_HREF = re.compile(r'\bhref\s*=\s*(?:"[^"]*\r|\'[^\']*\r)', re.I)


class Buffer(ctypes.Structure):
    _fields_ = [('data', ctypes.c_void_p), ('length', ctypes.c_size_t),
                ('capacity', ctypes.c_size_t), ('status', ctypes.c_uint32)]


class RustParser:
    def __init__(self):
        name = ('turtleneck_activity_parser.dll' if sys.platform == 'win32' else
                'libturtleneck_activity_parser.dylib' if sys.platform == 'darwin' else
                'libturtleneck_activity_parser.so')
        self.path = Path(__file__).parent / 'target/release' / name
        self.library = ctypes.CDLL(str(self.path))
        self.library.activity_parse.argtypes = (ctypes.c_char_p, ctypes.c_size_t)
        self.library.activity_parse.restype = Buffer
        self.library.activity_free.argtypes = (Buffer,)
        self.library.activity_free.restype = None
        self.calls = self.fallbacks = 0

    def parse(self, html):
        self.calls += 1
        # HTML5 normalizes raw CRs in URL attributes; HTMLParser preserves them.
        if '\r' in html and CR_IN_HREF.search(html):
            return self.python_fallback(html)
        try:
            encoded = html.encode('utf-8')
        except UnicodeEncodeError:
            return self.python_fallback(html)
        buffer = self.library.activity_parse(encoded, len(encoded))
        try:
            if buffer.status in (1, 2):
                return self.python_fallback(html)
            if buffer.status:
                raise RuntimeError('Rust activity parser internal error')
            return json.loads(ctypes.string_at(buffer.data, buffer.length))
        finally:
            self.library.activity_free(buffer)

    def python_fallback(self, html):
        self.fallbacks += 1
        parser = PythonActivityParser()
        parser.feed(html)
        return parser.items


def parser_class(native):
    class RustActivityParser:
        def __init__(self):
            self.raw = ''
            self.items = []

        def feed(self, html):
            self.raw += html
            self.items = native.parse(self.raw)
    return RustActivityParser
