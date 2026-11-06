"""Experimental one-process Rust activity parser; production stays on Python."""
import ctypes
import json
from pathlib import Path
import re
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'skills/university-agent'))
from providers.moodle_provider import _ActivityParser as PythonActivityParser, _SectionOverviewParser as PythonOverviewParser
from features.concept_insights import _rank_bucket as PythonRankBucket

CR_IN_HREF = re.compile(r'\b(?:href|id)\s*=\s*(?:"[^"]*\r|\'[^\']*\r)', re.I)


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
        for name in ('activity_parse', 'overview_parse', 'concept_rank'):
            function = getattr(self.library, name)
            function.argtypes = (ctypes.c_char_p, ctypes.c_size_t)
            function.restype = Buffer
        self.library.activity_free.argtypes = (Buffer,)
        self.library.activity_free.restype = None
        self.calls = self.fallbacks = 0
        self.calls_by_kind = {'activity': 0, 'overview': 0}
        self.concept_calls = self.concept_fallbacks = 0

    def rank_concepts(self, bucket, limit):
        self.concept_calls += 1
        def fallback():
            self.concept_fallbacks += 1
            return PythonRankBucket(bucket, limit)
        try:
            if type(limit) is not int or not 1 <= limit <= 50:
                return fallback()
            rows = []
            for name, item in bucket.items():
                if not isinstance(name, str) or any(not isinstance(kind, str) for kind in item['sourceImportance']):
                    return fallback()
                rows.append({**item, 'concept': name, 'evidence': list(item['evidence'].values())})
            encoded = json.dumps({'rows': rows, 'limit': limit}, ensure_ascii=False, separators=(',', ':')).encode('utf-8')
        except (TypeError, ValueError, UnicodeEncodeError):
            return fallback()
        output = self.library.concept_rank(encoded, len(encoded))
        try:
            if output.status in (1, 2):
                return fallback()
            if output.status:
                raise RuntimeError('Rust concept ranking internal error')
            return json.loads(ctypes.string_at(output.data, output.length))
        finally:
            self.library.activity_free(output)

    def parse(self, html):
        return self._parse(html, 'activity')

    def overviews(self, html):
        return self._parse(html, 'overview')

    def _parse(self, html, kind):
        self.calls += 1
        self.calls_by_kind[kind] += 1
        # HTML5 normalizes raw CRs in URL attributes; HTMLParser preserves them.
        if '\r' in html and CR_IN_HREF.search(html):
            return self.python_fallback(html, kind)
        try:
            encoded = html.encode('utf-8')
        except UnicodeEncodeError:
            return self.python_fallback(html, kind)
        function = self.library.activity_parse if kind == 'activity' else self.library.overview_parse
        buffer = function(encoded, len(encoded))
        try:
            if buffer.status in (1, 2):
                return self.python_fallback(html, kind)
            if buffer.status:
                raise RuntimeError('Rust activity parser internal error')
            return json.loads(ctypes.string_at(buffer.data, buffer.length))
        finally:
            self.library.activity_free(buffer)

    def python_fallback(self, html, kind='activity'):
        self.fallbacks += 1
        parser = PythonActivityParser() if kind == 'activity' else PythonOverviewParser()
        parser.feed(html)
        return parser.items if kind == 'activity' else parser.overviews


def parser_class(native):
    class RustActivityParser:
        def __init__(self):
            self.raw = ''
            self.items = []

        def feed(self, html):
            self.raw += html
            self.items = native.parse(self.raw)
    return RustActivityParser


def overview_parser_class(native):
    class RustOverviewParser:
        def __init__(self):
            self.raw = ''
            self.overviews = []

        def feed(self, html):
            self.raw += html
            self.overviews = native.overviews(self.raw)
    return RustOverviewParser
