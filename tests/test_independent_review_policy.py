from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = (
    ROOT
    / "skills"
    / "explain-diff-for-human-review"
    / "scripts"
    / "validate_independent_review.py"
)


def _load_module():
    spec = importlib.util.spec_from_file_location("validate_independent_review", SCRIPT)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load {SCRIPT}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


class IndependentReviewPolicyTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.module = _load_module()

    def _payload(self, *, diff_mode: str = "small"):
        head_sha = "b" * 40
        return {
            "schema_version": 1,
            "status": "completed",
            "base_sha": "a" * 40,
            "head_sha": head_sha,
            "diff_mode": diff_mode,
            "included_paths": ["src/example.py"],
            "omitted_paths": [],
            "findings": [
                {
                    "severity": "medium",
                    "title": "Example finding",
                    "path": "src/example.py",
                    "symbol": "run",
                    "line_start": 10,
                    "line_end": 12,
                    "evidence_ref": f"src/example.py@{head_sha}:L10-L12",
                    "failure_scenario": "The operation can return stale state.",
                    "confidence": "high",
                    "recommended_validation": ["Run the focused regression test."],
                }
            ],
            "evidence_gaps": [],
        }

    def test_small_completed_review_is_valid(self):
        payload = self._payload()
        self.module.validate_independent_review(
            payload,
            expected_base_sha="a" * 40,
            expected_head_sha="b" * 40,
            expected_mode="small",
            expected_paths=["src/example.py"],
        )

    def test_standard_review_records_omitted_paths(self):
        payload = self._payload(diff_mode="standard")
        payload["omitted_paths"] = ["vendor/generated.js"]
        payload["evidence_gaps"] = ["Generated vendor file was not inspected."]
        self.module.validate_independent_review(
            payload,
            expected_mode="standard",
            expected_paths=["src/example.py", "vendor/generated.js"],
        )

    def test_unavailable_subagent_requires_disclosed_single_agent_fallback(self):
        payload = self._payload()
        payload.update(
            status="unavailable",
            included_paths=[],
            findings=[],
            evidence_gaps=["Subagent capability was unavailable; used single-agent review."],
        )
        self.module.validate_independent_review(payload)

    def test_failed_subagent_output_cannot_retain_findings(self):
        payload = self._payload()
        payload.update(
            status="failed",
            evidence_gaps=["Subagent execution failed; used single-agent review."],
        )
        with self.assertRaisesRegex(ValueError, "findings must be empty"):
            self.module.validate_independent_review(payload)

    def test_finding_evidence_must_be_pinned_to_head(self):
        payload = self._payload()
        payload["findings"][0]["evidence_ref"] = "src/example.py@main:L10-L12"
        with self.assertRaisesRegex(ValueError, "head_sha"):
            self.module.validate_independent_review(payload)

    def test_finding_evidence_path_must_match_finding_path(self):
        payload = self._payload()
        payload["findings"][0]["evidence_ref"] = (
            f"docs/other.md@{'b' * 40}:L10-L12"
        )
        with self.assertRaisesRegex(ValueError, "path"):
            self.module.validate_independent_review(payload)

    def test_finding_evidence_lines_must_match_finding_lines(self):
        payload = self._payload()
        payload["findings"][0]["evidence_ref"] = (
            f"src/example.py@{'b' * 40}:L1-L2"
        )
        with self.assertRaisesRegex(ValueError, "line range"):
            self.module.validate_independent_review(payload)

    def test_declared_coverage_must_match_expected_paths(self):
        payload = self._payload()
        with self.assertRaisesRegex(ValueError, "declared coverage"):
            self.module.validate_independent_review(
                payload,
                expected_paths=["src/example.py", "docs/other.md"],
            )

    def test_cli_validates_machine_readable_payload(self):
        payload = self._payload()
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "review.json"
            path.write_text(json.dumps(payload), encoding="utf-8")
            completed = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPT),
                    str(path),
                    "--expected-base-sha",
                    "a" * 40,
                    "--expected-head-sha",
                    "b" * 40,
                    "--expected-mode",
                    "small",
                    "--expected-path",
                    "src/example.py",
                ],
                check=True,
                capture_output=True,
                text=True,
            )
        self.assertEqual(json.loads(completed.stdout), {"valid": True})


if __name__ == "__main__":
    unittest.main()
