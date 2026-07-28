from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
SKILL_PATH = (
    ROOT / "skills" / "execute-github-issue-pr-workflow" / "SKILL.md"
)
MERGE_GATE_HEADING = "## Gate merge or staging"
MERGE_GATE_POLICIES = {
    "same_turn_merge_prohibited": (
        "Never merge a PR in the same assistant turn that created it."
    ),
    "timer_or_auto_merge_cannot_bypass": (
        "A timer or auto-merge setting cannot bypass this boundary."
    ),
    "approval_names_pr_base_and_head": (
        "request approval naming that PR, base SHA, and HEAD SHA"
    ),
    "base_or_head_change_invalidates_approval": (
        "any base or HEAD change invalidates the report and approval"
    ),
    "default_mode_requires_later_user_turn": (
        "Merge only in a later user turn."
    ),
    "automatic_staging_never_authorizes_merge": (
        "Automatic staging never authorizes merging."
    ),
    "merge_uses_reported_and_approved_shas": (
        "require base and HEAD to equal the reported and approved SHAs"
    ),
    "protection_and_force_push_cannot_be_bypassed": (
        "Never bypass protection or force-push."
    ),
}


def _section(markdown, heading):
    marker = f"{heading}\n"
    if marker not in markdown:
        raise ValueError(f"Missing section: {heading}")
    section = markdown.split(marker, 1)[1]
    next_heading = section.find("\n## ")
    if next_heading != -1:
        section = section[:next_heading]
    return section


def _missing_merge_gate_policies(markdown):
    gate = _section(markdown, MERGE_GATE_HEADING)
    return {
        name
        for name, policy in MERGE_GATE_POLICIES.items()
        if policy not in gate
    }


class MergeGatePolicyTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.skill = SKILL_PATH.read_text(encoding="utf-8")

    def test_human_merge_decision_policies_are_in_merge_gate(self):
        self.assertEqual(set(), _missing_merge_gate_policies(self.skill))

    def test_deleting_each_merge_gate_policy_is_detected(self):
        gate = _section(self.skill, MERGE_GATE_HEADING)
        for name, policy in MERGE_GATE_POLICIES.items():
            with self.subTest(policy=name):
                self.assertIn(policy, gate)
                mutated = self.skill.replace(policy, "", 1)
                self.assertIn(name, _missing_merge_gate_policies(mutated))


if __name__ == "__main__":
    unittest.main()
