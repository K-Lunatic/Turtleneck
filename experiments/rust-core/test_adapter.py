from concurrent.futures import ThreadPoolExecutor
import random
import unittest

from python_adapter import RustParser, PythonActivityParser, parser_class


def python_parse(html):
    parser = PythonActivityParser()
    parser.feed(html)
    return parser.items


class ParityTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.native = RustParser()

    def test_static_html_contracts(self):
        cases = [
            '', '<p>not an activity</p>',
            '<li class="activity modtype_resource"><a href="/x?a=1&amp;b=2">자료 &amp; 예제</a></li>',
            '<LI CLASS="activity"><A HREF="/X">대문자</A></LI>',
            '<li class="activity"><a href="/x"><span>중첩</span> 제목</a><ul><li>다운로드 금지</li></ul></li>',
            '<li class="activity"><a>첫 링크</a><a href="/two">두 번째</a></li>',
            '<li class="activity"><a href="/one">처음</a><a href="/two">나중</a></li>',
            '<li class="activity"><a href="/x"/>닫힌 앵커</li>',
            '<li class="activity"/>', '<li class="activity">닫히지 않은 항목',
            '<li class="activity"><script>var x = "<a>&amp;";</script><a href="/x">이름</a></li>',
            '<li class="activity"><style>.x > a {content:"&amp;"}</style><a href="/x">이름</a></li>',
            '<li class="activity"><a href="/x">&#x1F422; &#0; &unknown; &nbsp; &#13;</a></li>',
            '<li class="activity"><a href="/x">한글\x1c 이름\u0085끝</a>\x1d기타</li>',
            '<li class="activity"><a href="/x\r\ny">속성 줄바꿈</a></li>',
            '<li class="activity" class="other"><a href="/x">중복 속성</a></li>',
            '<li class="other" class="activity"><a href="/x">중복 역순</a></li>',
            '<li class="activity"><a href="/first" href="/last">URL 중복</a></li>',
            '<li class="activity"><a href="/x">\ud800</a></li>',
            '<li class="activity"><!-- comment --><a href="/x">\x00</a></li>',
        ]
        for html in cases:
            with self.subTest(html=ascii(html)):
                self.assertEqual(self.native.parse(html), python_parse(html))

    def test_generated_markup_matches(self):
        rng = random.Random(20261106)
        words = ['자료', '수업', 'A &amp; B', '&#x1F422;', 'text\r\nnext', '&nbsp;', '<b>굵게</b>']
        for index in range(200):
            title = ' '.join(rng.choices(words, k=rng.randint(1, 6)))
            html = f'<li class="activity modtype_resource"><a href="/file?id={index}&amp;x=2">{title}</a><span> 저장 금지 </span></li>'
            self.assertEqual(self.native.parse(html), python_parse(html))

    def test_fallback_preserves_duplicate_attribute_semantics(self):
        html = '<li class="other" class="activity"><a href="/x">자료</a></li>'
        previous = self.native.fallbacks
        self.assertEqual(self.native.parse(html), python_parse(html))
        self.assertEqual(self.native.fallbacks, previous + 1)

    def test_concurrent_calls_are_independent(self):
        inputs = [f'<li class="activity"><a href="/{i}">자료 {i}</a></li>' for i in range(100)]
        with ThreadPoolExecutor(max_workers=4) as pool:
            rows = list(pool.map(self.native.parse, inputs))
        self.assertEqual(rows, [python_parse(html) for html in inputs])

    def test_incremental_feed_keeps_completed_items(self):
        native = parser_class(self.native)()
        python = PythonActivityParser()
        for chunk in ('<li class="activity"><a href="/1">첫', ' 항목</a></li>', '<li class="activity">두 번째</li>'):
            native.feed(chunk)
            python.feed(chunk)
            self.assertEqual(native.items, python.items)

    def test_ffi_rejects_invalid_utf8_and_input_size(self):
        for data, length in ((b'\xff', 1), (None, 32 * 1024 * 1024 + 1)):
            output = self.native.library.activity_parse(data, length)
            try:
                self.assertEqual(output.status, 1)
                self.assertFalse(output.data)
            finally:
                self.native.library.activity_free(output)


if __name__ == '__main__':
    unittest.main()
