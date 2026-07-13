from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]


class SkillPolicyTests(unittest.TestCase):
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
