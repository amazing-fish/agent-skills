from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
SKILL_ROOT = ROOT / "skills" / "douyin-video-analysis"


class DouyinVideoAnalysisPolicyTests(unittest.TestCase):
    def setUp(self):
        self.skill = (SKILL_ROOT / "SKILL.md").read_text(encoding="utf-8")
        self.framework = (
            SKILL_ROOT / "references" / "report-framework.md"
        ).read_text(encoding="utf-8")
        self.agent_metadata = (
            SKILL_ROOT / "agents" / "openai.yaml"
        ).read_text(encoding="utf-8")

    def test_package_contains_only_required_skill_files(self):
        files = {
            path.relative_to(SKILL_ROOT).as_posix()
            for path in SKILL_ROOT.rglob("*")
            if path.is_file()
        }
        self.assertEqual(
            {
                "SKILL.md",
                "agents/openai.yaml",
                "references/report-framework.md",
            },
            files,
        )

    def test_skill_preserves_evidence_and_failure_boundaries(self):
        for required_policy in (
            "free/local speech-to-text first",
            "Extract 3-7 key frames",
            "Separate evidence from interpretation",
            "Never invent exact quotes",
            'do not stop at "failed"',
            "produce a partial report",
        ):
            with self.subTest(required_policy=required_policy):
                self.assertIn(required_policy, self.skill)

    def test_skill_does_not_assume_parser_runtime_is_bundled(self):
        self.assertIn("This Skill does not bundle a parser runtime", self.skill)
        self.assertIn("If a compatible parser exists", self.skill)
        self.assertNotIn("For this workspace, use", self.skill)

    def test_example_writes_generated_artifacts_to_ignored_reports(self):
        ignore_rules = (ROOT / ".gitignore").read_text(encoding="utf-8")
        self.assertIn("**/reports/", ignore_rules)
        self.assertIn(
            '--out "reports/douyin-video-analysis/<run-id>"',
            self.skill,
        )
        self.assertNotIn("--out outputs/", self.skill)

    def test_report_contract_is_learning_oriented(self):
        for required_section in (
            "## 1. Source Summary",
            "## 2. Core Conclusion",
            "## 4. Terminology",
            "## 5. Techniques And Principles",
            "## 6. Learning Path",
            "## 7. Validation Boundaries",
        ):
            with self.subTest(required_section=required_section):
                self.assertIn(required_section, self.framework)
        self.assertIn("not for dumping the raw transcript", self.framework)

    def test_agent_metadata_matches_skill(self):
        for required_metadata in (
            'display_name: "抖音视频分析"',
            'short_description: "Analyze Douyin video links into evidence-backed reports"',
            "Use $douyin-video-analysis",
        ):
            with self.subTest(required_metadata=required_metadata):
                self.assertIn(required_metadata, self.agent_metadata)


if __name__ == "__main__":
    unittest.main()
