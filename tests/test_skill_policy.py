import json
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

    def test_goal_prompt_routing_contract_spans_workflow_optimizer_and_readme(self):
        workflow = (
            ROOT / "skills" / "execute-github-issue-pr-workflow" / "SKILL.md"
        ).read_text(encoding="utf-8")
        optimizer = (
            ROOT / "skills" / "optimize-prompt" / "SKILL.md"
        ).read_text(encoding="utf-8")
        readme = (ROOT / "README.md").read_text(encoding="utf-8")
        cases = json.loads(
            (
                ROOT / "tests" / "fixtures" / "goal_prompt_routing_cases.json"
            ).read_text(encoding="utf-8")
        )

        expected_cases = {
            "workflow_optimize_and_proceed": (
                "execute-github-issue-pr-workflow",
                "orchestrated_child",
                "used",
                True,
                True,
                True,
                False,
            ),
            "standalone_optimize_only": (
                "optimize-prompt",
                "standalone",
                "not_applicable",
                False,
                False,
                False,
                False,
            ),
            "workflow_prompt_only": (
                "execute-github-issue-pr-workflow",
                "orchestrated_child",
                "used",
                True,
                False,
                False,
                False,
            ),
            "workflow_child_failure": (
                "execute-github-issue-pr-workflow",
                "single_agent_fallback",
                "fallback",
                False,
                True,
                True,
                False,
            ),
        }
        observed_cases = {
            case["id"]: (
                case["parent"],
                case["optimizer_mode"],
                case["preflight_status"],
                case["independent_child"],
                case["implementation_authorized"],
                case["parent_continues"],
                case["generated_prompt_grants_authority"],
            )
            for case in cases
        }
        self.assertEqual(expected_cases, observed_cases)

        for case_id in expected_cases:
            with self.subTest(case_id=case_id):
                self.assertIn(f"`{case_id}`", workflow)

        for required_policy in (
            "The parent workflow owns routing",
            "must not replace the workflow's final delivery",
            "emit `goal-prompt preflight:` followed by exactly one of `used`, `skipped`, or `fallback`",
        ):
            with self.subTest(workflow_policy=required_policy):
                self.assertIn(required_policy, workflow)

        for required_policy in (
            "Standalone invocation",
            "Orchestrated child invocation",
            "separate-follow-up requirement does not transfer to the parent workflow",
        ):
            with self.subTest(optimizer_policy=required_policy):
                self.assertIn(required_policy, optimizer)

        for required_policy in (
            "standalone prompt optimization",
            "workflow-owned preflight",
            "original user request",
        ):
            with self.subTest(readme_policy=required_policy):
                self.assertIn(required_policy, readme)

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
