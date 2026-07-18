from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]


class SkillPolicyTests(unittest.TestCase):
    def test_optimize_prompt_preserves_grounding_and_outcome_boundaries(self):
        skill = (
            ROOT / "skills" / "optimize-prompt" / "SKILL.md"
        ).read_text(encoding="utf-8")
        for required_policy in (
            "source-only mode",
            "context-grounded mode",
            "never complete the downstream deliverable",
            "require a separate follow-up before execution",
            "Never continue from the optimized prompt into execution",
        ):
            with self.subTest(required_policy=required_policy):
                self.assertIn(required_policy, skill)

    def test_goal_prompt_preflight_preserves_optional_authorization_and_fallback_boundaries(self):
        skill = (
            ROOT / "skills" / "execute-github-issue-pr-workflow" / "SKILL.md"
        ).read_text(encoding="utf-8")
        for required_policy in (
            "Only enable this preflight when",
            "Skip this preflight for a simple, well-bounded Issue",
            "Do not provide the main Agent's expected solution",
            "remain read-only",
            "does not establish facts or grant authorization",
            "single-Agent fallback",
        ):
            with self.subTest(required_policy=required_policy):
                self.assertIn(required_policy, skill)

    def test_github_diff_policy_is_links_only(self):
        skill = (
            ROOT / "skills" / "explain-diff-for-human-review" / "SKILL.md"
        ).read_text(encoding="utf-8")
        self.assertIn(
            "一律不在 HTML 中复制 raw diff、patch 或 diff hunk",
            skill,
        )

    def test_independent_review_preserves_read_only_and_fallback_boundaries(self):
        skill = (
            ROOT / "skills" / "explain-diff-for-human-review" / "SKILL.md"
        ).read_text(encoding="utf-8")
        for required_policy in (
            "不要提供主 Agent 的预期结论",
            "只读",
            "不修改产品代码",
            "单 Agent 回退",
            "validate_independent_review.py",
        ):
            with self.subTest(required_policy=required_policy):
                self.assertIn(required_policy, skill)


if __name__ == "__main__":
    unittest.main()
