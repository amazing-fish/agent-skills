from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT_DIR = ROOT / "skills" / "explain-diff-for-human-review" / "scripts"


def _load_module(name: str):
    path = SCRIPT_DIR / f"{name}.py"
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


class ResolveReportPathTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.module = _load_module("resolve_report_path")

    def test_explicit_file_has_highest_precedence(self):
        with tempfile.TemporaryDirectory() as temp:
            explicit = Path(temp) / "chosen.html"
            result = self.module.resolve_report_path(
                target="pr-2",
                output_path=str(explicit),
                repository_root=str(Path(temp) / "repo"),
            )
            self.assertEqual(Path(result.path), explicit.resolve())
            self.assertEqual(result.source, "explicit")

    def test_explicit_directory_gets_generated_filename(self):
        with tempfile.TemporaryDirectory() as temp:
            result = self.module.resolve_report_path(
                target="PR #2 / output",
                output_path=temp,
            )
            self.assertEqual(Path(result.path).name, "explain-diff-PR-2-output.html")
            self.assertEqual(result.source, "explicit")

    def test_repository_precedes_workspace(self):
        with tempfile.TemporaryDirectory() as temp:
            repository = Path(temp) / "repo"
            workspace = Path(temp) / "workspace"
            result = self.module.resolve_report_path(
                target="commit-abc",
                repository_root=str(repository),
                workspace_root=str(workspace),
            )
            self.assertEqual(
                Path(result.path),
                (repository / "reports" / "explain-diff-commit-abc.html").resolve(),
            )
            self.assertEqual(result.source, "repository")

    def test_workspace_precedes_temporary_root(self):
        with tempfile.TemporaryDirectory() as temp:
            workspace = Path(temp) / "workspace"
            result = self.module.resolve_report_path(
                target="branch",
                workspace_root=str(workspace),
                temporary_root=str(Path(temp) / "tmp"),
            )
            self.assertEqual(result.source, "workspace")
            self.assertTrue(Path(result.path).parent.is_dir())

    def test_temporary_fallback_is_writable_and_report_scoped(self):
        with tempfile.TemporaryDirectory() as temp:
            result = self.module.resolve_report_path(
                target="target",
                temporary_root=temp,
            )
            self.assertEqual(result.source, "temporary")
            self.assertEqual(Path(result.path).parent, (Path(temp) / "reports").resolve())
            self.assertTrue(Path(result.path).parent.is_dir())


class DiffSizePolicyTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.module = _load_module("classify_diff_size")

    def test_small_boundary_is_inclusive(self):
        result = self.module.classify_diff_size(
            changed_files=20,
            changed_lines=800,
            patch_bytes=128 * 1024,
        )
        self.assertEqual(result.mode, "small")
        self.assertEqual(result.detail_delivery, "inline")

    def test_one_metric_over_small_selects_standard(self):
        result = self.module.classify_diff_size(
            changed_files=21,
            changed_lines=800,
            patch_bytes=128 * 1024,
        )
        self.assertEqual(result.mode, "standard")

    def test_standard_boundary_is_inclusive(self):
        result = self.module.classify_diff_size(
            changed_files=80,
            changed_lines=4_000,
            patch_bytes=1024 * 1024,
        )
        self.assertEqual(result.mode, "standard")

    def test_one_metric_over_standard_selects_large(self):
        result = self.module.classify_diff_size(
            changed_files=80,
            changed_lines=4_001,
            patch_bytes=1024 * 1024,
        )
        self.assertEqual(result.mode, "large")

    def test_github_small_uses_pinned_links_only(self):
        result = self.module.classify_diff_size(
            changed_files=3,
            changed_lines=20,
            patch_bytes=500,
            host="github.com",
        )
        self.assertEqual(result.mode, "small")
        self.assertEqual(result.detail_delivery, "pinned-github-links-only")

    def test_github_standard_uses_pinned_links_only(self):
        result = self.module.classify_diff_size(
            changed_files=21,
            changed_lines=801,
            patch_bytes=128 * 1024 + 1,
            host="GitHub",
        )
        self.assertEqual(result.mode, "standard")
        self.assertEqual(result.detail_delivery, "pinned-github-links-only")

    def test_github_large_uses_pinned_links_only(self):
        result = self.module.classify_diff_size(
            changed_files=100,
            changed_lines=10_000,
            patch_bytes=2 * 1024 * 1024,
            host="github.com",
        )
        self.assertEqual(result.mode, "large")
        self.assertEqual(result.detail_delivery, "pinned-github-links-only")

    def test_github_dot_com_fqdn_is_normalized(self):
        result = self.module.classify_diff_size(
            changed_files=21,
            changed_lines=801,
            patch_bytes=128 * 1024 + 1,
            host=" GitHub.COM. ",
        )
        self.assertEqual(result.detail_delivery, "pinned-github-links-only")

    def test_non_github_hostname_does_not_match_by_suffix(self):
        result = self.module.classify_diff_size(
            changed_files=21,
            changed_lines=801,
            patch_bytes=128 * 1024 + 1,
            host="notgithub.com",
        )
        self.assertEqual(result.detail_delivery, "collapsed-bounded-details")

    def test_unavailable_patch_marks_evidence_incomplete(self):
        result = self.module.classify_diff_size(
            changed_files=3,
            changed_lines=20,
            patch_bytes=500,
            unavailable_patches=1,
        )
        self.assertFalse(result.evidence_complete)
        self.assertIn("unavailable_patches=1", result.reasons)

    def test_cli_emits_machine_readable_json(self):
        completed = subprocess.run(
            [
                sys.executable,
                str(SCRIPT_DIR / "classify_diff_size.py"),
                "--changed-files",
                "81",
                "--changed-lines",
                "200",
                "--patch-bytes",
                "1000",
                "--host",
                "github.com",
            ],
            check=True,
            capture_output=True,
            text=True,
        )
        payload = json.loads(completed.stdout)
        self.assertEqual(payload["mode"], "large")
        self.assertEqual(
            payload["detail_delivery"],
            "pinned-github-links-only",
        )

    def test_negative_metric_is_rejected(self):
        with self.assertRaises(ValueError):
            self.module.classify_diff_size(
                changed_files=-1,
                changed_lines=0,
                patch_bytes=0,
            )


if __name__ == "__main__":
    unittest.main()
