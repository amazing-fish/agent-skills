from pathlib import Path
import re
import unittest

ROOT = Path(__file__).resolve().parents[1]
SKILL = ROOT / "skills" / "explain-diff-for-human-review"


class VisualReportPolicyTests(unittest.TestCase):
    def test_modes_keep_pr_brief_as_default(self):
        text = (SKILL / "SKILL.md").read_text(encoding="utf-8")
        self.assertIn("`decision-brief`（默认）", text)
        self.assertIn("`visual-explanation`（按需）", text)
        self.assertIn("仅要求 HTML 不自动升级为长报告", text)
        self.assertIn("纯系统讲解不强造合入结论或虚构 PR", text)
        self.assertIn("模式选择不授予代码修改、发布或合入权限", text)
        for ref in re.findall(r"\]\(((?:references|assets)/[^)]+)\)", text):
            self.assertTrue((SKILL / ref).is_file(), ref)

    def test_explanation_preserves_evidence_and_control_boundaries(self):
        text = (SKILL / "references" / "visual-explanation.md").read_text(encoding="utf-8")
        for requirement in (
            "接口条件／规范要求", "上游当前实现", "单条记录采集时间",
            "计划触发、实际启动与完成时间", "已在用户客户端复现",
            "不证明上游已产生新数据", "不请求网络、不改配置",
            "无脚本", "打印", "textContent", "aria-live",
        ):
            with self.subTest(requirement=requirement):
                self.assertIn(requirement, text)

    def test_visual_styles_are_opt_in_and_reuse_semantic_theme(self):
        css = (SKILL / "assets" / "visual-explanation.css").read_text(encoding="utf-8")
        self.assertIn(".visual-report", css)
        self.assertNotRegex(css, r"#[0-9a-fA-F]{3,8}\b|rgba?\(")
        self.assertNotIn("url(", css)
        self.assertNotIn("@import", css)
        self.assertNotRegex(css, r"(?:^|\n)(?:body|html|\.report-shell|\.report-nav)\s*\{")
        for required in ("@media print", "prefers-reduced-motion", "max-width: 760px", "visual-static-states", "min-height: 44px"):
            self.assertIn(required, css)


if __name__ == "__main__":
    unittest.main()
