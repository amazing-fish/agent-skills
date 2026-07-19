import json
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]


def _routing_case_tuple(case):
    return (
        case["parent"],
        case["optimizer_mode"],
        case["preflight_status"],
        case["independent_child"],
        case["implementation_authorized"],
        case["parent_continues"],
        case["generated_prompt_grants_authority"],
    )


def _parse_routing_contract(workflow, optimizer, expected_ids):
    parent_names = {
        "workflow": "execute-github-issue-pr-workflow",
        "optimizer": "optimize-prompt",
    }
    child_modes = {"independent": True, "no_child": False}
    authority_states = {"authorized": True, "not_authorized": False}
    outcomes = {"continue": True, "stop": False}
    prompt_grants_authority = not (
        "neither the generated prompt nor the child output can add"
        in workflow.lower()
        and "child output cannot grant" in optimizer.lower()
    )
    observed = {}

    for line in workflow.splitlines():
        cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
        if not cells or not cells[0].startswith("`"):
            continue
        case_id = cells[0].strip("`")
        if case_id not in expected_ids:
            continue
        if len(cells) != 6:
            raise ValueError(f"Unexpected routing row shape for {case_id}")

        route = cells[2].strip("`").split("/")
        if len(route) != 3:
            raise ValueError(f"Unexpected route shape for {case_id}")
        observed[case_id] = (
            parent_names[route[0]],
            route[1],
            cells[3].strip("`"),
            child_modes[route[2]],
            authority_states[cells[4].strip("`")],
            outcomes[cells[5].strip("`")],
            prompt_grants_authority,
        )

    return observed


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

        expected_cases = {case["id"]: _routing_case_tuple(case) for case in cases}
        observed_cases = _parse_routing_contract(
            workflow,
            optimizer,
            expected_cases.keys(),
        )
        self.assertEqual(expected_cases, observed_cases)

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

    def test_goal_prompt_routing_contract_detects_outcome_reversals(self):
        workflow = (
            ROOT / "skills" / "execute-github-issue-pr-workflow" / "SKILL.md"
        ).read_text(encoding="utf-8")
        optimizer = (
            ROOT / "skills" / "optimize-prompt" / "SKILL.md"
        ).read_text(encoding="utf-8")
        cases = json.loads(
            (
                ROOT / "tests" / "fixtures" / "goal_prompt_routing_cases.json"
            ).read_text(encoding="utf-8")
        )
        expected_cases = {case["id"]: _routing_case_tuple(case) for case in cases}

        mutations = (
            ("`authorized` | `continue` |", "`authorized` | `stop` |"),
            ("`not_authorized` | `stop` |", "`not_authorized` | `continue` |"),
        )
        for original, replacement in mutations:
            with self.subTest(replacement=replacement):
                mutated = workflow.replace(original, replacement, 1)
                self.assertNotEqual(workflow, mutated)
                self.assertNotEqual(
                    expected_cases,
                    _parse_routing_contract(
                        mutated,
                        optimizer,
                        expected_cases.keys(),
                    ),
                )

    def test_github_diff_policy_is_links_only(self):
        skill = (
            ROOT / "skills" / "explain-diff-for-human-review" / "SKILL.md"
        ).read_text(encoding="utf-8")
        self.assertIn(
            "一律不在 HTML 中复制 raw diff、patch 或 diff hunk",
            skill,
        )

    def test_github_mutable_target_uses_snapshot_evidence_contract(self):
        skill = (
            ROOT / "skills" / "explain-diff-for-human-review" / "SKILL.md"
        ).read_text(encoding="utf-8")
        contract = (
            ROOT
            / "skills"
            / "explain-diff-for-human-review"
            / "references"
            / "diff-evidence-contract.md"
        ).read_text(encoding="utf-8")
        for required_policy in (
            "mutable-local-snapshot",
            "fixed_compare_covers_target=false",
            "不得用 zero-diff compare 作为改动证据",
            "不要为了给 mutable snapshot 制造永久链接",
        ):
            with self.subTest(required_policy=required_policy):
                self.assertIn(required_policy, skill)
        for material in (
            "Untracked text",
            "Binary",
            "Generated/vendor",
            "Submodule gitlink",
            "Ignored",
            "Missing patch or material",
            "Truncated patch or material",
        ):
            with self.subTest(material=material):
                self.assertIn(f"| {material} |", contract)

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
