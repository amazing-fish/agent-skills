import copy
from html.parser import HTMLParser
import importlib.util
import json
from pathlib import Path
import sys
import unittest


ROOT = Path(__file__).resolve().parents[1]
SKILL = ROOT / "skills" / "report-for-human"


def _load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(mod)
    return mod


renderer = _load_module("dual_mode_renderer", SKILL / "scripts" / "render_dual_mode_report.py")
validator = _load_module("dual_mode_validator", SKILL / "scripts" / "validate_dual_mode_report.py")


class TagParser(HTMLParser):
    def __init__(self, html_text: str):
        super().__init__()
        self.tags = []
        self.feed(html_text)

    def handle_starttag(self, tag, attrs):
        self.tags.append((tag, dict(attrs)))


class DualModeReportTests(unittest.TestCase):
    def _example(self, mode: str) -> dict:
        return json.loads((SKILL / "examples" / f"{mode}.example.json").read_text(encoding="utf-8"))

    def test_approval_and_handoff_examples_render_and_validate_cleanly(self):
        for mode in ("approval", "handoff"):
            with self.subTest(mode=mode):
                data = self._example(mode)
                html_out = renderer.render_report(data, mode)
                errors, warnings = validator.validate_html(html_out, expected_mode=mode)
                self.assertEqual(errors, [])
                self.assertEqual(warnings, [])
                self.assertIn(f'data-report-mode="{mode}"', html_out)
                self.assertIn("report-for-human@v2.0.0", html_out)

    def test_xss_payload_is_escaped_in_html_and_embedded_json(self):
        payload = "</script><img src=x onerror=alert(1)>"
        for mode in ("approval", "handoff"):
            with self.subTest(mode=mode):
                data = copy.deepcopy(self._example(mode))
                data["meta"]["report_title"] = payload
                data["prs"][0]["summary"] = payload
                data["prompt"]["preamble"] = payload
                html_out = renderer.render_report(data, mode)
                parsed = TagParser(html_out)
                self.assertFalse(any(tag == "img" for tag, _ in parsed.tags))
                self.assertNotIn("<img src=x", html_out)
                errors, _ = validator.validate_html(html_out, expected_mode=mode)
                self.assertEqual(errors, [])

    def test_non_http_url_raises_value_error(self):
        data = copy.deepcopy(self._example("approval"))
        data["meta"]["main_head_url"] = "javascript:alert(1)"
        with self.assertRaises(ValueError):
            renderer.render_report(data, "approval")

    def test_validator_rejects_mode_mismatch_external_cdn_and_placeholders(self):
        approval_html = renderer.render_report(self._example("approval"), "approval")
        errors_mismatch, _ = validator.validate_html(approval_html, expected_mode="handoff")
        self.assertTrue(any("模式不匹配" in err for err in errors_mismatch))

        cdn_html = approval_html.replace("</head>", '<link href="https://cdn.tailwindcss.com/test.css"></head>')
        errors_cdn, _ = validator.validate_html(cdn_html, expected_mode="approval")
        self.assertTrue(any("外网" in err or "CDN" in err for err in errors_cdn))

        placeholder_html = approval_html + "<div>{{UNRESOLVED_SLOT}}</div>"
        errors_ph, _ = validator.validate_html(placeholder_html, expected_mode="approval")
        self.assertTrue(any("占位符" in err for err in errors_ph))

    def test_skill_md_links_dual_mode_reference_and_respects_line_limit(self):
        skill_md = (SKILL / "SKILL.md").read_text(encoding="utf-8")
        self.assertIn("references/dual-mode-handoff.md", skill_md)
        self.assertTrue((SKILL / "references" / "dual-mode-handoff.md").is_file())
        self.assertLessEqual(len(skill_md.splitlines()), 100)


if __name__ == "__main__":
    unittest.main()
