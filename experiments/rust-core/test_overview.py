from concurrent.futures import ThreadPoolExecutor
import random
import unittest
from python_adapter import RustParser, PythonOverviewParser, overview_parser_class


def python_overviews(html):
    parser = PythonOverviewParser()
    parser.feed(html)
    return parser.overviews


class OverviewParityTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.native = RustParser()

    def test_static_visibility_and_structure_contracts(self):
        cases = [
            '', '<li class="section">짧은 한글</li>',
            '<li class="section" id="s" aria-label="1주차">1주차 : 수업 개요와 일정에 관한 충분히 긴 안내입니다.</li>',
            '<li class="section">수업 개요와 일정에 관한 충분히 긴 안내입니다.<span hidden>노출 금지</span></li>',
            '<li class="section"><div style=" DISPLAY : NONE">노출 금지</div>공개된 수업 설명이 충분히 길게 있습니다.</li>',
            '<li class="section">수업 설명이 충분히 길게 있습니다.<li class="activity"><a href="/x">활동 설명 제외</a><ul><li>중첩 활동 제외</li></ul></li>계속되는 설명입니다.</li>',
            '<li class="section"><script>"<a>숨김</a>"</script><style>숨김</style>공개된 충분히 긴 수업 설명입니다.</li>',
            '<li class="section"><span aria-hidden="true"><b>숨긴 설명</b></span>공개된 충분히 긴 수업 설명입니다.</li>',
            '<li class="section"><span class="sr-only">숨긴 설명</span><br/>공개된 충분히 긴 수업 설명입니다.</li>',
            '<li class="section" aria-label="이름">이름 — 충분히 긴 수업 설명과 참고 사항입니다.</li>',
            '<li class="section"><li class="section">중첩 섹션 설명이 충분히 길게 있습니다.</li></li>',
            '<li class="activity section">클래스가 겹치는 수업 설명입니다.</li>',
            '<li class="section">수업 &amp; 예제&nbsp;참고 설명이 충분히 깁니다.</li>',
            '<li class="section" id="a\r\nb">공개된 충분히 긴 수업 설명입니다.</li>',
            '<li class="section" class="other">공개된 충분히 긴 수업 설명입니다.</li>',
            '<li class="section">공개된 충분히 긴 수업 설명입니다.',
            '<li class="section"><div hidden>숨김</li>노출 여부 확인',
            '<li class="section">공개된 충분히 긴 수업 설명입니다.\ud800</li>',
        ]
        for html in cases:
            with self.subTest(html=ascii(html)):
                self.assertEqual(self.native.overviews(html), python_overviews(html))

    def test_generated_sections_match(self):
        rng = random.Random(20261106)
        hidden = ['hidden', 'aria-hidden="true"', 'class="accesshide"', 'style="visibility: hidden"', '']
        for index in range(200):
            html = f'<li class="section" id="s{index}" aria-label="주차 {index}">주차 {index}: 수업 개요와 일정에 관한 충분히 긴 안내입니다.'
            html += f'<span {rng.choice(hidden)}>추가 내용도 길게 포함되어 있습니다.</span>'
            html += '<li class="activity"><a href="/x">자료 설명</a></li></li>'
            self.assertEqual(self.native.overviews(html), python_overviews(html))

    def test_incremental_feed_and_concurrent_requests(self):
        parser = overview_parser_class(self.native)()
        original = PythonOverviewParser()
        for chunk in ('<li class="section">개요와', ' 일정에 관한 충분히 긴 설명입니다.</li>'):
            parser.feed(chunk)
            original.feed(chunk)
            self.assertEqual(parser.overviews, original.overviews)
        pages = [f'<li class="section">수업 {index}에 관한 충분히 긴 설명입니다.</li>' for index in range(100)]
        with ThreadPoolExecutor(max_workers=4) as pool:
            result = list(pool.map(self.native.overviews, pages))
        self.assertEqual(result, [python_overviews(page) for page in pages])


if __name__ == '__main__':
    unittest.main()
