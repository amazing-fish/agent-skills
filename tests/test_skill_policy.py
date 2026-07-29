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


def _parse_markdown_table_rows(markdown, expected_ids, *, column_count):
    expected_ids = set(expected_ids)
    observed = {}

    for line in markdown.splitlines():
        cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
        if len(cells) != column_count or not cells[0].startswith("`"):
            continue
        case_id = cells[0].strip("`")
        if case_id not in expected_ids:
            continue
        if case_id in observed:
            raise ValueError(
                f"Duplicate {column_count}-column row for {case_id}"
            )
        observed[case_id] = tuple(cell.strip("`") for cell in cells[1:])

    return observed


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

    rows = _parse_markdown_table_rows(
        workflow,
        expected_ids,
        column_count=6,
    )
    for case_id, cells in rows.items():
        route = cells[1].split("/")
        if len(route) != 3:
            raise ValueError(f"Unexpected route shape for {case_id}")
        observed[case_id] = (
            parent_names[route[0]],
            route[1],
            cells[2],
            child_modes[route[2]],
            authority_states[cells[3]],
            outcomes[cells[4]],
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

    def test_markdown_table_parser_uses_explicit_column_count(self):
        markdown = """
| Case | A | B | C | D |
| --- | --- | --- | --- | --- |
| `shared_case` | `one` | `two` | `three` | `four` |

| Case | A | B | C | D | E |
| --- | --- | --- | --- | --- | --- |
| `shared_case` | `one` | `two` | `three` | `four` | `five` |
"""
        self.assertEqual(
            {"shared_case": ("one", "two", "three", "four")},
            _parse_markdown_table_rows(
                markdown,
                {"shared_case"},
                column_count=5,
            ),
        )
        self.assertEqual(
            {"shared_case": ("one", "two", "three", "four", "five")},
            _parse_markdown_table_rows(
                markdown,
                {"shared_case"},
                column_count=6,
            ),
        )

    def test_review_timer_contract_is_packaged_with_skill(self):
        workflow = (
            ROOT / "skills" / "execute-github-issue-pr-workflow" / "SKILL.md"
        ).read_text(encoding="utf-8")
        contract_path = (
            ROOT
            / "skills"
            / "execute-github-issue-pr-workflow"
            / "references"
            / "review-timer-contract.json"
        )
        cases = json.loads(
            contract_path.read_text(encoding="utf-8")
        )
        self.assertFalse(
            (
                ROOT / "tests" / "fixtures" / "review_timer_cases.json"
            ).exists()
        )
        self.assertEqual(len(cases), len({case["id"] for case in cases}))
        for case in cases:
            self.assertEqual(
                {"id", "surface", "evidence", "schedule_basis", "outcome"},
                set(case),
            )
        for required_policy in (
            "[the review timer contract](references/review-timer-contract.json)",
            "If this Skill contains `scripts/resolve_review_timer.py`, prefer it",
            "use a heartbeat attached to the current thread",
            "derive `BYHOUR`, `BYMINUTE`, `BYSECOND`, and `BYDAY` from `target_at_utc` in UTC",
            "Never copy the user's local wall-clock fields into the RRULE.",
            "Do not fall back to local wall-clock fields",
            "differs from `target_at_utc` by at most 60 seconds",
            "delete that exact timer immediately",
            "target local time, target time zone, and verified next run",
        ):
            with self.subTest(required_policy=required_policy):
                self.assertIn(required_policy, workflow)

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
