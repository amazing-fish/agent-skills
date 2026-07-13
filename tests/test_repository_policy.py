from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]


class RepositoryPolicyTests(unittest.TestCase):
    def test_pr_creation_turn_cannot_merge(self):
        policy = (ROOT / "AGENTS.md").read_text(encoding="utf-8")
        self.assertIn(
            "A pull request opened during the current turn is ineligible for both "
            "direct merge and auto-merge until a later user turn.",
            policy,
        )

    def test_review_feedback_defaults_to_existing_pr(self):
        policy = (ROOT / "AGENTS.md").read_text(encoding="utf-8")
        self.assertIn(
            "Fix actionable review feedback on the existing pull request branch",
            policy,
        )

    def test_github_diff_policy_is_links_only(self):
        skill = (
            ROOT / "skills" / "explain-diff-for-human-review" / "SKILL.md"
        ).read_text(encoding="utf-8")
        self.assertIn(
            "一律不在 HTML 中复制 raw diff、patch 或 diff hunk",
            skill,
        )


if __name__ == "__main__":
    unittest.main()
