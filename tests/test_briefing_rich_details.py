import copy
from html.parser import HTMLParser
import importlib.util
import json
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
SKILL = ROOT / "skills" / "report-for-human"


def _load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(mod)
    return mod


renderer = _load_module("report_v21_renderer_rich", SKILL / "scripts" / "render_report.py")
validator = _load_module("report_v21_validator_rich", SKILL / "scripts" / "validate_report.py")


class _DomInspector(HTMLParser):
    def __init__(self, html_text: str):
        super().__init__()
        self.tags = []
        self.feed(html_text)
        self.close()

    def handle_starttag(self, tag, attrs):
        self.tags.append((tag, dict(attrs)))


class BriefingRichDetailsTests(unittest.TestCase):
    def _briefing_example(self) -> dict:
        return json.loads((SKILL / "examples" / "briefing.example.json").read_text(encoding="utf-8"))

    def test_sanitizer_blocks_hostile_inputs_and_preserves_safe_tables(self):
        cases = [
            ("A<script>alert(1)</script>B", "AB"),
            ('<div onclick="steal()">t</div>', "<div>t</div>"),
            ('<a href="javascript:x">l</a>', "l"),
            ("<img src=x onerror=alert(1)>", ""),
            ('<p style="color:red">p</p>', "<p>p</p>"),
            ("<marquee>m</marquee>", "m"),
            ("a < b & c", "a &lt; b &amp; c"),
            (
                '<table class="tbl"><thead><tr><th scope="col">周</th><th>WAU</th></tr></thead>'
                "<tbody><tr><td>W0</td><td>144,524</td></tr></tbody></table>",
                '<table class="tbl"><thead><tr><th scope="col">周</th><th>WAU</th></tr></thead>'
                "<tbody><tr><td>W0</td><td>144,524</td></tr></tbody></table>",
            ),
            # Void dropped element must not swallow trailing text
            ('<input type="text" value="x">after', "after"),
            # Unmatched closing tags cannot break out of .inv-details-body
            ("</div></details></article><p>ok</p>", "<p>ok</p>"),
            # Unclosed tags are balanced automatically
            ("<table><tr><td>cell", "<table><tr><td>cell</td></tr></table>"),
            # Reserved framework class names are stripped while safe user classes remain
            ('<div class="kpi-card tbl bad$cls">x</div>', '<div class="tbl">x</div>'),
            # Attribute scoping: colspan/rowspan only on th/td with positive int; open only on details
            (
                '<div colspan="2" open><details open><summary>s</summary>'
                '<table><tr><td colspan="2" rowspan="0">c</td></tr></table></details></div>',
                '<div><details open><summary>s</summary>'
                '<table><tr><td colspan="2">c</td></tr></table></details></div>',
            ),
        ]
        for raw, expected in cases:
            with self.subTest(raw=raw):
                self.assertEqual(renderer.sanitize_rich_html(raw), expected)

    def test_briefing_inventory_renders_real_table_and_strips_tags_from_search_text(self):
        data = copy.deepcopy(self._briefing_example())
        data["inventory"][0]["details"] = (
            '<table class="tbl"><tr><th>周</th><th>WAU</th></tr>'
            "<tr><td>W0</td><td>144,524</td></tr></table>"
            "<script>secret_token()</script>"
        )
        html_out = renderer.render_report(data, "briefing")
        errors, warnings = validator.validate_html(html_out, expected_mode="briefing")
        self.assertEqual(errors, [])
        self.assertEqual(warnings, [])

        self.assertIn('<table class="tbl">', html_out)
        self.assertIn("<th>周</th><th>WAU</th>", html_out)
        self.assertNotIn("&lt;table", html_out)
        self.assertNotIn("secret_token", html_out.split('<script id="report-data"')[0])

        # data-search-text keeps cell text without HTML tag noise or dropped script content
        dom = _DomInspector(html_out)
        inv_cards = [attrs for tag, attrs in dom.tags if tag == "article" and "inv-card" in attrs.get("class", "")]
        self.assertTrue(inv_cards)
        search_text = inv_cards[0].get("data-search-text", "")
        self.assertIn("144,524", search_text)
        self.assertNotIn("<table", search_text)
        self.assertNotIn("secret_token", search_text)

    def test_plain_text_details_remain_backward_compatible(self):
        data = copy.deepcopy(self._briefing_example())
        data["inventory"][0]["details"] = "仅纯文本：a < b & c > d"
        html_out = renderer.render_report(data, "briefing")
        self.assertIn("仅纯文本：a &lt; b &amp; c &gt; d", html_out)
        errors, warnings = validator.validate_html(html_out, expected_mode="briefing")
        self.assertEqual(errors, [])
        self.assertEqual(warnings, [])

    def test_validator_catches_escaped_table_markup_and_allows_code_example(self):
        data = copy.deepcopy(self._briefing_example())
        data["inventory"][0]["details"] = '<table class="tbl"><tr><th>K</th></tr><tr><td>V</td></tr></table>'
        clean_html = renderer.render_report(data, "briefing")
        self.assertEqual(validator.validate_html(clean_html, expected_mode="briefing")[0], [])

        # Simulate regression where details was html.escape()'d instead of sanitized
        escaped_html = clean_html.replace(
            '<table class="tbl"><tr><th>K</th></tr><tr><td>V</td></tr></table>',
            '&lt;table class="tbl"&gt;&lt;tr&gt;&lt;th&gt;K&lt;/th&gt;&lt;/tr&gt;&lt;tr&gt;&lt;td&gt;V&lt;/td&gt;&lt;/tr&gt;&lt;/table&gt;',
        )
        errs, _ = validator.validate_html(escaped_html, expected_mode="briefing")
        self.assertTrue(any("转义为纯文本源码" in e for e in errs), errs)

        # Inline <code>&lt;table&gt;</code> documentation inside details must not false-positive
        code_data = copy.deepcopy(self._briefing_example())
        code_data["inventory"][0]["details"] = (
            "<p>支持使用 <code>&lt;table&gt;</code> 渲染表格：</p>"
            "<table><tr><th>列</th></tr><tr><td>值</td></tr></table>"
        )
        code_html = renderer.render_report(code_data, "briefing")
        self.assertEqual(validator.validate_html(code_html, expected_mode="briefing")[0], [])

    def test_coderabbit_round1_fixes_placeholders_wrapper_event_and_per_item_validation(self):
        # 1. Plain-text placeholders like <branch> are preserved in both rendered HTML and search text
        data = copy.deepcopy(self._briefing_example())
        data["inventory"][0]["details"] = "运行 git checkout <branch> 并在 <owner>/<repo> 核对"
        data["inventory"][1]["details"] = "<table class=\"raw\">keep literal</table>"
        data["inventory"][1]["details_format"] = "plain"
        html_out = renderer.render_report(data, "briefing")
        errors, warnings = validator.validate_html(html_out, expected_mode="briefing")
        self.assertEqual(errors, [])
        self.assertEqual(warnings, [])
        self.assertIn("git checkout &lt;branch&gt;", html_out)
        self.assertIn("&lt;owner&gt;/&lt;repo&gt;", html_out)
        self.assertIn("&lt;table class=&quot;raw&quot;&gt;keep literal&lt;/table&gt;", html_out)
        dom = _DomInspector(html_out)
        inv_cards = [attrs for tag, attrs in dom.tags if tag == "article" and "inv-card" in attrs.get("class", "")]
        self.assertIn("git checkout <branch>", inv_cards[0].get("data-search-text", ""))

        # Invalid details_format raises ValueError
        bad_fmt = copy.deepcopy(self._briefing_example())
        bad_fmt["inventory"][0]["details_format"] = "markdown"
        with self.assertRaises(ValueError):
            renderer.render_report(bad_fmt, "briefing")

        # 2. Event handler on .inv-details-body wrapper itself must be rejected by validator
        wrapper_xss = html_out.replace(
            '<div class="inv-details-body" data-inv-index="0">',
            '<div class="inv-details-body" data-inv-index="0" onclick="alert(1)">',
            1,
        )
        wrapper_errs, _ = validator.validate_html(wrapper_xss, expected_mode="briefing")
        self.assertTrue(any("内联事件处理器" in e for e in wrapper_errs), wrapper_errs)

        # 3. Literal &lt;table&gt; in item 0 must NOT false-positive when item 2 has a real <table>
        mixed = copy.deepcopy(self._briefing_example())
        mixed["inventory"][0]["details"] = "<p>Literal &lt;table&gt; token</p>"
        mixed["inventory"][2]["details"] = '<table class="tbl"><tr><th>K</th></tr><tr><td>V</td></tr></table>'
        mixed_html = renderer.render_report(mixed, "briefing")
        self.assertEqual(validator.validate_html(mixed_html, expected_mode="briefing")[0], [])

        # Still fails if item 2's own real <table> was escaped
        broken_item2 = mixed_html.replace(
            '<table class="tbl"><tr><th>K</th></tr><tr><td>V</td></tr></table>',
            '&lt;table class="tbl"&gt;&lt;tr&gt;&lt;th&gt;K&lt;/th&gt;&lt;/tr&gt;&lt;tr&gt;&lt;td&gt;V&lt;/td&gt;&lt;/tr&gt;&lt;/table&gt;',
        )
        item2_errs, _ = validator.validate_html(broken_item2, expected_mode="briefing")
        self.assertTrue(any("转义为纯文本源码" in e for e in item2_errs), item2_errs)


if __name__ == "__main__":
    unittest.main()
