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


renderer = _load_module("report_v21_renderer_bc", SKILL / "scripts" / "render_report.py")
validator = _load_module("report_v21_validator_bc", SKILL / "scripts" / "validate_report.py")


class _BehaviorVisibilityInspector(HTMLParser):
    def __init__(self, html_text: str):
        super().__init__()
        self.details_depth = 0
        self.behavior_blocks_in_details = 0
        self.behavior_blocks_visible = 0
        self.search_texts = []
        self.feed(html_text)
        self.close()

    def handle_starttag(self, tag, attrs):
        attr_map = dict(attrs)
        if tag == "details":
            self.details_depth += 1
        if attr_map.get("data-rfh-role") == "behavior-changes":
            if self.details_depth > 0:
                self.behavior_blocks_in_details += 1
            else:
                self.behavior_blocks_visible += 1
        if tag == "article" and "pr-card" in attr_map.get("class", ""):
            self.search_texts.append(attr_map.get("data-search-text", ""))

    def handle_endtag(self, tag):
        if tag == "details" and self.details_depth > 0:
            self.details_depth -= 1


class BehaviorChangesTests(unittest.TestCase):
    def _example(self, mode: str) -> dict:
        return json.loads((SKILL / "examples" / f"{mode}.example.json").read_text(encoding="utf-8"))

    def _sample_entry(self) -> dict:
        return {
            "capability": "批量导出取消后的临时文件清理",
            "before": "取消导出后保留未完成临时文件，下次启动自动续传。",
            "after": "取消导出后立即删除临时文件并要求重新导出。",
            "impact": "避免损坏半成品残留，但大任务误取消后无法断点续传。",
            "recovery": "启用 `--keep-partial-export` 参数可恢复旧的断点续传行为。",
            "source": "PR #201",
            "objection_status": "待人工确认取舍",
        }

    def test_behavior_changes_are_always_visible_outside_details_in_approval_and_handoff(self):
        for mode in ("approval", "handoff"):
            with self.subTest(mode=mode):
                data = copy.deepcopy(self._example(mode))
                data["prs"][0]["behavior_changes"] = [self._sample_entry()]
                html_out = renderer.render_report(data, mode)

                errors, warnings = validator.validate_html(html_out, expected_mode=mode)
                self.assertEqual(errors, [])
                self.assertEqual(warnings, [])

                inspector = _BehaviorVisibilityInspector(html_out)
                self.assertGreaterEqual(inspector.behavior_blocks_visible, 1)
                self.assertEqual(inspector.behavior_blocks_in_details, 0)

                for expected_text in (
                    "批量导出取消后的临时文件清理",
                    "取消导出后保留未完成临时文件",
                    "无法断点续传",
                    "--keep-partial-export",
                    "PR #201",
                    "待人工确认取舍",
                ):
                    self.assertIn(expected_text, html_out)

                if mode == "handoff":
                    self.assertTrue(any("无法断点续传" in s for s in inspector.search_texts))

    def test_omitting_behavior_changes_remains_backward_compatible(self):
        for mode in ("approval", "handoff"):
            with self.subTest(mode=mode):
                data = copy.deepcopy(self._example(mode))
                for pr in data["prs"]:
                    pr.pop("behavior_changes", None)
                html_out = renderer.render_report(data, mode)
                self.assertNotIn('data-rfh-role="behavior-changes"', html_out)
                errors, warnings = validator.validate_html(html_out, expected_mode=mode)
                self.assertEqual(errors, [])
                self.assertEqual(warnings, [])

    def test_behavior_changes_escapes_html_and_rejects_invalid_structures(self):
        data = copy.deepcopy(self._example("approval"))
        entry = self._sample_entry()
        entry["impact"] = '<img src=x onerror=alert(1)>'
        data["prs"][0]["behavior_changes"] = [entry]
        html_out = renderer.render_report(data, "approval")
        self.assertNotIn("<img src=x", html_out)
        self.assertIn("&lt;img src=x onerror=alert(1)&gt;", html_out)

        bad_non_list = copy.deepcopy(self._example("approval"))
        bad_non_list["prs"][0]["behavior_changes"] = "invalid"
        with self.assertRaises(ValueError):
            renderer.render_report(bad_non_list, "approval")

        bad_missing_field = copy.deepcopy(self._example("handoff"))
        incomplete = self._sample_entry()
        incomplete["recovery"] = "   "
        bad_missing_field["prs"][0]["behavior_changes"] = [incomplete]
        with self.assertRaises(ValueError):
            renderer.render_report(bad_missing_field, "handoff")


if __name__ == "__main__":
    unittest.main()
