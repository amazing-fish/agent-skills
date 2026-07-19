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


def _git(repository: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", "-C", str(repository), *args],
        check=True,
        capture_output=True,
        text=True,
    )


def _create_repository(root: Path) -> Path:
    repository = root / "repository"
    repository.mkdir()
    _git(repository, "init")
    _git(repository, "config", "user.email", "tests@example.invalid")
    _git(repository, "config", "user.name", "Policy Tests")
    (repository / "tracked.txt").write_text("before\n", encoding="utf-8")
    _git(repository, "add", "tracked.txt")
    _git(repository, "commit", "-m", "initial")
    return repository


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
        self.assertEqual(result.evidence_mode, "immutable-git")
        self.assertTrue(result.fixed_compare_covers_target)

    def test_github_worktree_uses_local_snapshot_disclosure(self):
        result = self.module.classify_diff_size(
            changed_files=1,
            changed_lines=2,
            patch_bytes=100,
            host="github.com",
            target_kind="working-tree",
        )
        self.assertEqual(result.evidence_mode, "mutable-local-snapshot")
        self.assertEqual(
            result.detail_delivery,
            "local-snapshot-metadata-only",
        )
        self.assertFalse(result.fixed_compare_covers_target)
        self.assertFalse(result.evidence_complete)

    def test_clean_github_worktree_is_complete_without_a_compare_claim(self):
        result = self.module.classify_diff_size(
            changed_files=0,
            changed_lines=0,
            patch_bytes=0,
            host="github.com",
            target_kind="working-tree",
        )
        self.assertEqual(result.evidence_mode, "mutable-local-snapshot")
        self.assertTrue(result.fixed_compare_covers_target)
        self.assertTrue(result.evidence_complete)

    def test_github_worktree_with_committed_only_diff_has_no_permalink_gap(self):
        result = self.module.classify_diff_size(
            changed_files=1,
            changed_lines=2,
            patch_bytes=100,
            host="github.com",
            target_kind="working-tree",
            permalink_gap_files=0,
        )
        self.assertTrue(result.fixed_compare_covers_target)
        self.assertTrue(result.evidence_complete)

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

    def test_cli_distinguishes_mutable_github_target(self):
        completed = subprocess.run(
            [
                sys.executable,
                str(SCRIPT_DIR / "classify_diff_size.py"),
                "--changed-files",
                "1",
                "--changed-lines",
                "2",
                "--patch-bytes",
                "100",
                "--host",
                "github.com",
                "--target-kind",
                "staged",
            ],
            check=True,
            capture_output=True,
            text=True,
        )
        payload = json.loads(completed.stdout)
        self.assertEqual(payload["evidence_mode"], "mutable-local-snapshot")
        self.assertFalse(payload["fixed_compare_covers_target"])
        self.assertFalse(payload["evidence_complete"])

    def test_negative_metric_is_rejected(self):
        with self.assertRaises(ValueError):
            self.module.classify_diff_size(
                changed_files=-1,
                changed_lines=0,
                patch_bytes=0,
            )

    def test_unknown_target_kind_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "target_kind"):
            self.module.classify_diff_size(
                changed_files=0,
                changed_lines=0,
                patch_bytes=0,
                target_kind="branch",
            )

    def test_permalink_gap_cannot_exceed_changed_files(self):
        with self.assertRaisesRegex(ValueError, "permalink_gap_files"):
            self.module.classify_diff_size(
                changed_files=1,
                changed_lines=0,
                patch_bytes=0,
                target_kind="working-tree",
                permalink_gap_files=2,
            )


class GitSnapshotPolicyTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.module = _load_module("capture_git_snapshot")

    def test_tracked_worktree_modification_has_stable_snapshot_identity(self):
        with tempfile.TemporaryDirectory() as temp:
            repository = _create_repository(Path(temp))
            (repository / "tracked.txt").write_text(
                "after\nsecond\n",
                encoding="utf-8",
            )

            first = self.module.capture_git_snapshot(
                repository=repository,
                target_kind="working-tree",
            )
            second = self.module.capture_git_snapshot(
                repository=repository,
                target_kind="working-tree",
            )

            self.assertEqual(first.snapshot_id, second.snapshot_id)
            self.assertRegex(first.snapshot_id, r"^sha256:[0-9a-f]{64}$")
            self.assertEqual(first.changed_files, 1)
            self.assertEqual(first.changed_lines, 3)
            self.assertEqual(first.uncommitted_paths, ("tracked.txt",))
            self.assertEqual(first.permalink_gap_paths, ("tracked.txt",))
            self.assertEqual(first.permalink_gap_files, 1)
            self.assertEqual(first.unavailable_patches, 0)

    def test_untracked_text_counts_lines_and_bytes_without_source_output(self):
        with tempfile.TemporaryDirectory() as temp:
            repository = _create_repository(Path(temp))
            content = "one\ntwo\n"
            (repository / "notes.txt").write_text(content, encoding="utf-8")

            result = self.module.capture_git_snapshot(
                repository=repository,
                target_kind="working-tree",
            )
            payload = json.loads(self.module.snapshot_to_json(result))

            self.assertEqual(result.changed_files, 1)
            self.assertEqual(result.changed_lines, 2)
            self.assertGreaterEqual(result.patch_bytes, len(content.encode("utf-8")))
            self.assertEqual(result.unavailable_patches, 0)
            self.assertEqual(result.entries[0].material, "text")
            self.assertNotIn(content, json.dumps(payload))

    def test_untracked_binary_and_generated_are_metadata_only(self):
        with tempfile.TemporaryDirectory() as temp:
            repository = _create_repository(Path(temp))
            (repository / "asset.bin").write_bytes(b"\x00\x01\x02")
            generated = repository / "generated.txt"
            generated.write_text("generated\nlines\n", encoding="utf-8")

            unclassified = self.module.capture_git_snapshot(
                repository=repository,
                target_kind="working-tree",
            )
            result = self.module.capture_git_snapshot(
                repository=repository,
                target_kind="working-tree",
                generated_paths=("generated.txt",),
            )

            self.assertEqual(result.changed_files, 2)
            self.assertEqual(result.changed_lines, 2)
            self.assertEqual(result.unavailable_patches, 2)
            self.assertEqual(
                result.metadata_only_paths,
                ("asset.bin", "generated.txt"),
            )
            self.assertFalse(result.local_evidence_complete)
            self.assertGreaterEqual(result.patch_bytes, 3 + len(generated.read_bytes()))
            self.assertEqual(result.generated_paths, ("generated.txt",))
            self.assertNotEqual(result.snapshot_id, unclassified.snapshot_id)

    def test_clean_head_equals_base_is_a_complete_zero_change_snapshot(self):
        with tempfile.TemporaryDirectory() as temp:
            repository = _create_repository(Path(temp))

            result = self.module.capture_git_snapshot(
                repository=repository,
                target_kind="working-tree",
            )

            self.assertEqual(result.base_sha, result.head_sha)
            self.assertEqual(result.changed_files, 0)
            self.assertEqual(result.changed_lines, 0)
            self.assertEqual(result.patch_bytes, 0)
            self.assertEqual(result.uncommitted_paths, ())
            self.assertEqual(result.permalink_gap_paths, ())
            self.assertEqual(result.permalink_gap_files, 0)
            self.assertTrue(result.local_evidence_complete)

    def test_clean_worktree_against_older_base_has_only_committed_evidence(self):
        with tempfile.TemporaryDirectory() as temp:
            repository = _create_repository(Path(temp))
            base_sha = _git(repository, "rev-parse", "HEAD").stdout.strip()
            (repository / "tracked.txt").write_text("committed\n", encoding="utf-8")
            _git(repository, "add", "tracked.txt")
            _git(repository, "commit", "-m", "committed change")

            result = self.module.capture_git_snapshot(
                repository=repository,
                target_kind="working-tree",
                base=base_sha,
            )

            self.assertEqual(result.changed_files, 1)
            self.assertEqual(result.permalink_gap_files, 0)
            self.assertEqual(result.permalink_gap_paths, ())
            self.assertEqual(result.entries[0].coverage, "immutable-head")

    def test_staged_target_excludes_unstaged_and_untracked_material(self):
        with tempfile.TemporaryDirectory() as temp:
            repository = _create_repository(Path(temp))
            tracked = repository / "tracked.txt"
            tracked.write_text("staged\n", encoding="utf-8")
            _git(repository, "add", "tracked.txt")
            tracked.write_text("unstaged\n", encoding="utf-8")
            (repository / "untracked.txt").write_text("outside\n", encoding="utf-8")

            result = self.module.capture_git_snapshot(
                repository=repository,
                target_kind="staged",
            )

            self.assertEqual(result.changed_files, 1)
            self.assertEqual(result.uncommitted_paths, ("tracked.txt",))
            self.assertEqual(tuple(entry.path for entry in result.entries), ("tracked.txt",))

    def test_ignored_material_is_excluded_unless_explicitly_scoped(self):
        with tempfile.TemporaryDirectory() as temp:
            repository = _create_repository(Path(temp))
            (repository / ".gitignore").write_text("ignored.txt\n", encoding="utf-8")
            _git(repository, "add", ".gitignore")
            _git(repository, "commit", "-m", "ignore generated material")
            (repository / "ignored.txt").write_text("ignored\n", encoding="utf-8")

            default = self.module.capture_git_snapshot(
                repository=repository,
                target_kind="working-tree",
            )
            explicit = self.module.capture_git_snapshot(
                repository=repository,
                target_kind="working-tree",
                included_ignored_paths=("ignored.txt",),
            )

            self.assertEqual(default.changed_files, 0)
            self.assertEqual(explicit.changed_files, 1)
            self.assertEqual(explicit.included_ignored_paths, ("ignored.txt",))
            self.assertEqual(explicit.entries[0].status, "!")

    def test_cli_emits_machine_readable_snapshot_without_content(self):
        with tempfile.TemporaryDirectory() as temp:
            repository = _create_repository(Path(temp))
            secret_marker = "local-only-marker"
            (repository / "notes.txt").write_text(secret_marker, encoding="utf-8")

            completed = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPT_DIR / "capture_git_snapshot.py"),
                    "--repository",
                    str(repository),
                    "--target-kind",
                    "working-tree",
                ],
                check=True,
                capture_output=True,
                text=True,
            )
            payload = json.loads(completed.stdout)
            self.assertEqual(payload["schema_version"], 1)
            self.assertEqual(payload["target_kind"], "working-tree")
            self.assertNotIn(secret_marker, completed.stdout)

    def test_explicit_ignored_path_must_stay_repository_relative(self):
        with tempfile.TemporaryDirectory() as temp:
            repository = _create_repository(Path(temp))
            with self.assertRaisesRegex(ValueError, "repository-relative"):
                self.module.capture_git_snapshot(
                    repository=repository,
                    target_kind="working-tree",
                    included_ignored_paths=("C:/outside.txt",),
                )


if __name__ == "__main__":
    unittest.main()
