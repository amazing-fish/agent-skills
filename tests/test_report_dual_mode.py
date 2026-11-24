import copy
from html.parser import HTMLParser
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
SKILL = ROOT / "skills" / "report-for-human"


def _load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(mod)
    return mod


renderer = _load_module("report_v21_renderer", SKILL / "scripts" / "render_report.py")
validator = _load_module("report_v21_validator", SKILL / "scripts" / "validate_report.py")


class TagParser(HTMLParser):
    def __init__(self, html_text: str):
        super().__init__()
        self.tags = []
        self.feed(html_text)

    def handle_starttag(self, tag, attrs):
        self.tags.append((tag, dict(attrs)))


class ReportV21Tests(unittest.TestCase):
    def _example(self, mode: str) -> dict:
        return json.loads((SKILL / "examples" / f"{mode}.example.json").read_text(encoding="utf-8"))

    def test_all_three_modes_render_and_validate_cleanly(self):
        for mode in ("approval", "handoff", "briefing"):
            with self.subTest(mode=mode):
                data = self._example(mode)
                html_out = renderer.render_report(data, mode)
                errors, warnings = validator.validate_html(html_out, expected_mode=mode)
                self.assertEqual(errors, [])
                self.assertEqual(warnings, [])
                self.assertIn(f'data-report-mode="{mode}"', html_out)
                self.assertIn("report-for-human@v2.1.0", html_out)

    def test_xss_payload_is_escaped_in_html_and_embedded_json(self):
        payload = "</script><img src=x onerror=alert(1)>"
        for mode in ("approval", "handoff", "briefing"):
            with self.subTest(mode=mode):
                data = copy.deepcopy(self._example(mode))
                data["meta"]["report_title"] = payload
                if mode in ("approval", "handoff"):
                    data["prs"][0]["summary"] = payload
                else:
                    data["gaps"][0]["current_state"] = payload
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

    def test_validator_rejects_mode_mismatch_cdn_tab_entity_svg_image_and_placeholders(self):
        approval_html = renderer.render_report(self._example("approval"), "approval")
        errors_mismatch, _ = validator.validate_html(approval_html, expected_mode="handoff")
        self.assertTrue(any("模式不匹配" in err for err in errors_mismatch))

        for bad_snippet in (
            '<link href="https://cdn.tailwindcss.com/test.css">',
            '<script src="//example.org/report.js"></script>',
            '<script src=//example.org/report.js></script>',
            '<img src="https:&#9;//example.org/pixel.png">',
            '<svg><image href="https://example.org/pixel.png" width="1" height="1"/></svg>',
            '<svg><use xlink:href="https://example.org/sprite.svg#icon"/></svg>',
            '<style>@import url("//example.org/a.css");</style>',
        ):
            with self.subTest(bad_snippet=bad_snippet):
                errs, _ = validator.validate_html(approval_html.replace("</head>", bad_snippet + "</head>"), expected_mode="approval")
                self.assertTrue(any("外网" in err or "CSS" in err for err in errs), errs)

        placeholder_html = approval_html + "<div>{{UNRESOLVED_SLOT}}</div>"
        errors_ph, _ = validator.validate_html(placeholder_html, expected_mode="approval")
        self.assertTrue(any("占位符" in err for err in errors_ph))

    def test_validator_allows_domain_mentions_in_prose_and_same_doc_svg_fragments(self):
        data = copy.deepcopy(self._example("handoff"))
        data["prs"][0]["summary"] = "Remove unpkg.com dependency and drop cdnjs.cloudflare.com ref"
        clean_html = renderer.render_report(data, "handoff")
        with_local_svg_use = clean_html.replace("</body>", '<svg><use href="#local-def"/></svg></body>')
        errs_clean, warns_clean = validator.validate_html(with_local_svg_use, expected_mode="handoff")
        self.assertEqual(errs_clean, [])
        self.assertEqual(warns_clean, [])

    def test_validator_checks_mandatory_dimensions_with_void_inputs_and_briefing_gaps(self):
        approval_html = renderer.render_report(self._example("approval"), "approval")
        broken_approval = approval_html.replace("解锁效果与残余卡点", "缺失维度占位")
        errs_a, _ = validator.validate_html(broken_approval, expected_mode="approval")
        self.assertTrue(any("缺少必填维度" in e for e in errs_a), errs_a)

        briefing_html = renderer.render_report(self._example("briefing"), "briefing")
        broken_briefing = briefing_html.replace("核心卡点 / 债务", "缺失维度占位")
        errs_b, _ = validator.validate_html(broken_briefing, expected_mode="briefing")
        self.assertTrue(any("缺少必填维度" in e for e in errs_b), errs_b)

    def test_skill_md_links_schema_and_respects_line_limit(self):
        skill_md = (SKILL / "SKILL.md").read_text(encoding="utf-8")
        self.assertIn("references/data-schema.md", skill_md)
        self.assertTrue((SKILL / "references" / "data-schema.md").is_file())
        self.assertLessEqual(len(skill_md.splitlines()), 100)

    def test_approval_gate_honors_authorized_field_and_rejects_null_criterion(self):
        data = copy.deepcopy(self._example("approval"))
        data["gates"] = [{
            "id": "G-AUTH",
            "title": "Test Authorized Gate",
            "description": "Authorized gate should start enabled",
            "url": "https://github.com/amazing-fish/agent-skills/pull/78",
            "authorized": True,
        }]
        html_out = renderer.render_report(data, "approval")
        self.assertIn('data-gate-id="G-AUTH" role="switch" checked', html_out)
        self.assertIn("门禁 1/1", html_out)
        self.assertIn("- [已授权] Test Authorized Gate（G-AUTH）", html_out)

        bad = copy.deepcopy(self._example("approval"))
        bad["criteria"][0]["target_and_status"] = None
        with self.assertRaises(ValueError):
            renderer.render_report(bad, "approval")

    def test_templates_hardening_keyboard_topology_filter_and_prompt_mode_normalization(self):
        approval_html = renderer.render_report(self._example("approval"), "approval")
        self.assertNotIn("warnEl.innerHTML", approval_html)
        self.assertIn("document.createTextNode(", approval_html)
        self.assertNotIn("'.dag-node[data-svg-pr-id=\"'", approval_html)
        self.assertIn('class="dag-node', approval_html)
        self.assertIn('tabindex="0" role="button"', approval_html)
        self.assertIn("e.key === 'Enter' || e.key === ' '", approval_html)

        data = copy.deepcopy(self._example("handoff"))
        data["prompt"]["modes"] = [
            {"id": 1, "label": "Mode 1", "instructions": "Run mode 1"},
            {"id": 2, "label": "Mode 2", "instructions": "Run mode 2"},
        ]
        data["prompt"]["default_mode"] = 2
        handoff_html = renderer.render_report(data, "handoff")
        self.assertIn("(state.filterStatus === 'blocked' && st === 'deferred')", handoff_html)
        self.assertIn("String(m.id) === String(state.promptMode)", handoff_html)
        self.assertIn('data-prompt-mode="2" aria-pressed="true"', handoff_html)

        briefing_html = renderer.render_report(self._example("briefing"), "briefing")
        self.assertIn('class="arch-node"', briefing_html)
        self.assertIn('tabindex="0" role="button"', briefing_html)
        self.assertIn('id="tab-btn-2" aria-controls="tab-panel-2" aria-selected="false" tabindex="-1"', briefing_html)
        self.assertIn('new Map()', briefing_html)
        self.assertIn("card.focus({ preventScroll: true })", briefing_html)
        self.assertIn("revealPromptForManualCopy()", briefing_html)
        self.assertIn('tabindex="-1"', briefing_html)

    def test_regressions_coderabbit_round2_hardening(self):
        # 1. Hostless URL rejection
        bad_url = copy.deepcopy(self._example("approval"))
        bad_url["meta"]["main_head_url"] = "https://"
        with self.assertRaises(ValueError):
            renderer.render_report(bad_url, "approval")

        # 2. Merged pill counts and JS filter include conflict_resolved consistently
        h_data = copy.deepcopy(self._example("handoff"))
        conflict_count = sum(1 for p in h_data["prs"] if p.get("status") in ("merged", "conflict_resolved"))
        h_html = renderer.render_report(h_data, "handoff")
        self.assertIn(f"已合入 ({conflict_count})", h_html)
        self.assertIn("(state.filterStatus === 'merged' && st === 'conflict_resolved')", h_html)

        # 3. 1 layer + 7 horizontals expands SVG viewBox and frame height cleanly
        b_data = copy.deepcopy(self._example("briefing"))
        b_data["architecture"]["layers"] = b_data["architecture"]["layers"][:1]
        b_data["architecture"]["horizontals"] = [
            {"id": f"H{i}", "name": f"Engine {i}", "detail": "detail"} for i in range(1, 8)
        ]
        b_html = renderer.render_report(b_data, "briefing")
        self.assertIn("1 层纵向架构 + 7 项横向平台能力（SVG）", b_html)
        # horizontal_span = 48 + 7*36 + 6*10 = 360; svg_h >= 406 (> 320)
        self.assertIn('viewBox="0 0 1040 406"', b_html)

        # 4. Deterministic generated_at fallback + literal {{SSR_ARCH_SVG}} preserved + zero_artifact_constraint baseline kept
        det_data = copy.deepcopy(self._example("briefing"))
        det_data["meta"].pop("generated_at", None)
        det_data["prompt"]["preamble"] = "Keep literal {{SSR_ARCH_SVG}} inside prose"
        det_data["prompt"]["zero_artifact_constraint"] = "自定义补充：仅汇报 SHA"
        det_html_1 = renderer.render_report(det_data, "briefing")
        det_html_2 = renderer.render_report(det_data, "briefing")
        self.assertEqual(det_html_1, det_html_2)
        self.assertIn("未提供（not supplied）", det_html_1)
        self.assertIn("Keep literal {{SSR_ARCH_SVG}} inside prose", det_html_1)
        self.assertIn("零图片/零文件回传约束：严禁", det_html_1)
        self.assertIn("自定义补充：仅汇报 SHA", det_html_1)
        errs, warns = validator.validate_html(det_html_1, expected_mode="briefing")
        self.assertEqual(errs, [])
        self.assertEqual(warns, [])

        # 5. File-relative URLs rejected & scoped DOM + gap-box checks enforced
        rel_img = det_html_1.replace("</head>", '<img src="diagram.png"></head>')
        rel_errs, _ = validator.validate_html(rel_img, expected_mode="briefing")
        self.assertTrue(any("diagram.png" in e for e in rel_errs), rel_errs)

        # Fake gap card with words only in title and empty body should fail
        approval_base = renderer.render_report(self._example("briefing"), "briefing")
        first_blocker = self._example("briefing")["gaps"][0]["blocker"]
        empty_box_html = approval_base.replace(first_blocker, "")
        box_errs, _ = validator.validate_html(empty_box_html, expected_mode="briefing")
        self.assertTrue(any("维度块为空" in e for e in box_errs), box_errs)

        # Moving zero-artifact text outside element fails
        example_constraint = renderer.normalize_zero_artifact_constraint(
            self._example("briefing")["prompt"]["zero_artifact_constraint"]
        )
        outside_zero = approval_base.replace(
            f"<span><strong>硬性回传与脱敏约束（已锁定）：</strong>{renderer.esc(example_constraint)}</span>",
            f"<span>only text</span></div><div class='decoy'>{renderer.esc(example_constraint)}",
        )
        zero_errs, _ = validator.validate_html(outside_zero, expected_mode="briefing")
        self.assertTrue(any("zero-artifact-constraint" in e for e in zero_errs), zero_errs)

        # Scoped check: SVG outside svg-architecture or search input in Tab 3 must fail
        svg_elsewhere = approval_base.replace(
            '<div class="panel-section" data-rfh-role="svg-architecture">',
            '<div class="panel-section">',
        ).replace(
            '<svg class="architecture-svg"',
            '<svg class="decoy-svg"',
        )
        errs_svg_scope, _ = validator.validate_html(svg_elsewhere, expected_mode="briefing")
        self.assertTrue(any("SVG 分层架构图" in e for e in errs_svg_scope), errs_svg_scope)

    def test_cli_guards_same_file_and_validate_before_write(self):
        script = SKILL / "scripts" / "render_report.py"
        with tempfile.TemporaryDirectory() as tmp:
            tmp_dir = Path(tmp)
            bad_json = tmp_dir / "bad_briefing.json"
            data = copy.deepcopy(self._example("briefing"))
            data["gaps"] = []
            bad_json.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")

            # Same path input/output must fail without overwriting input JSON
            res_same = subprocess.run(
                [sys.executable, str(script), "--mode", "briefing", "--input", str(bad_json), "--output", str(bad_json)],
                capture_output=True, text=True, encoding="utf-8",
            )
            self.assertNotEqual(res_same.returncode, 0)
            self.assertIn("覆盖输入", res_same.stderr)
            self.assertTrue(json.loads(bad_json.read_text(encoding="utf-8"))["mode"] == "briefing")

            # Pre-existing report file must stay untouched when validation fails
            existing_out = tmp_dir / "report.html"
            existing_out.write_text("KEEP_EXISTING_REPORT", encoding="utf-8")
            res_fail = subprocess.run(
                [sys.executable, str(script), "--mode", "briefing", "--input", str(bad_json), "--output", str(existing_out)],
                capture_output=True, text=True, encoding="utf-8",
            )
            self.assertEqual(res_fail.returncode, 1)
            self.assertEqual(existing_out.read_text(encoding="utf-8"), "KEEP_EXISTING_REPORT")


if __name__ == "__main__":
    unittest.main()
