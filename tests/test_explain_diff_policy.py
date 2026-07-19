from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
import tempfile
import unittest
from unittest import mock
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

    def test_permalink_gap_can_exceed_base_relative_changed_files(self):
        result = self.module.classify_diff_size(
            changed_files=0,
            changed_lines=0,
            patch_bytes=0,
            host="github.com",
            target_kind="working-tree",
            permalink_gap_files=1,
        )
        self.assertFalse(result.fixed_compare_covers_target)
        self.assertFalse(result.evidence_complete)

    def test_negative_permalink_gap_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "permalink_gap_files"):
            self.module.classify_diff_size(
                changed_files=0,
                changed_lines=0,
                patch_bytes=0,
                target_kind="working-tree",
                permalink_gap_files=-1,
            )


class GitSnapshotPolicyTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.module = _load_module("capture_git_snapshot")
        cls.classifier = _load_module("classify_diff_size")

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

    def test_head_drift_after_final_capture_is_rejected(self):
        with tempfile.TemporaryDirectory() as temp:
            repository = _create_repository(Path(temp))
            _git(repository, "commit", "--allow-empty", "-m", "movable head")
            original_capture = self.module._capture_material
            capture_count = 0

            def capture_then_move_head(*args, **kwargs):
                nonlocal capture_count
                material = original_capture(*args, **kwargs)
                capture_count += 1
                if capture_count == 3:
                    _git(repository, "reset", "--soft", "HEAD^")
                return material

            with mock.patch.object(
                self.module,
                "_capture_material",
                side_effect=capture_then_move_head,
            ):
                with self.assertRaisesRegex(RuntimeError, "HEAD changed"):
                    self.module.capture_git_snapshot(
                        repository=repository,
                        target_kind="working-tree",
                    )

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

    def test_generated_directory_classifies_descendants_as_metadata_only(self):
        with tempfile.TemporaryDirectory() as temp:
            repository = _create_repository(Path(temp))
            vendor = repository / "vendor"
            vendor.mkdir()
            (vendor / "library.js").write_text(
                "export const value = 1;\n",
                encoding="utf-8",
            )

            result = self.module.capture_git_snapshot(
                repository=repository,
                target_kind="working-tree",
                generated_paths=("vendor",),
            )

            self.assertEqual(result.changed_files, 1)
            self.assertEqual(result.unavailable_patches, 1)
            self.assertFalse(result.local_evidence_complete)
            self.assertEqual(result.generated_paths, ("vendor/library.js",))
            self.assertEqual(result.entries[0].material, "generated")
            self.assertEqual(result.entries[0].coverage, "metadata-only")

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

    def test_base_relative_cancellation_keeps_head_permalink_gap(self):
        with tempfile.TemporaryDirectory() as temp:
            repository = _create_repository(Path(temp))
            base_sha = _git(repository, "rev-parse", "HEAD").stdout.strip()
            tracked = repository / "tracked.txt"
            tracked.write_text("committed\n", encoding="utf-8")
            _git(repository, "add", "tracked.txt")
            _git(repository, "commit", "-m", "committed change")

            tracked.write_text("before\n", encoding="utf-8")
            worktree = self.module.capture_git_snapshot(
                repository=repository,
                target_kind="working-tree",
                base=base_sha,
            )
            _git(repository, "add", "tracked.txt")
            staged = self.module.capture_git_snapshot(
                repository=repository,
                target_kind="staged",
                base=base_sha,
            )

            for snapshot in (worktree, staged):
                with self.subTest(target_kind=snapshot.target_kind):
                    self.assertEqual(snapshot.changed_files, 0)
                    self.assertEqual(snapshot.permalink_gap_files, 1)
                    self.assertEqual(snapshot.permalink_gap_paths, ("tracked.txt",))
                    decision = self.classifier.classify_diff_size(
                        changed_files=snapshot.changed_files,
                        changed_lines=snapshot.changed_lines,
                        patch_bytes=snapshot.patch_bytes,
                        unavailable_patches=snapshot.unavailable_patches,
                        host="github.com",
                        target_kind=snapshot.target_kind,
                        permalink_gap_files=snapshot.permalink_gap_files,
                    )
                    self.assertFalse(decision.fixed_compare_covers_target)
                    self.assertFalse(decision.evidence_complete)

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

    def test_path_scoped_snapshot_excludes_unrelated_local_material(self):
        with tempfile.TemporaryDirectory() as temp:
            repository = _create_repository(Path(temp))
            for name in ("staged.txt", "unstaged.txt"):
                (repository / name).write_text("before\n", encoding="utf-8")
            (repository / ".gitignore").write_text("ignored.txt\n", encoding="utf-8")
            _git(repository, "add", ".gitignore", "staged.txt", "unstaged.txt")
            _git(repository, "commit", "-m", "add scope fixtures")

            (repository / "tracked.txt").write_text("in scope\n", encoding="utf-8")
            (repository / "staged.txt").write_text("staged one\n", encoding="utf-8")
            _git(repository, "add", "staged.txt")
            (repository / "unstaged.txt").write_text("unstaged one\n", encoding="utf-8")
            (repository / "untracked.txt").write_text("untracked one\n", encoding="utf-8")
            (repository / "ignored.txt").write_text("ignored one\n", encoding="utf-8")

            first = self.module.capture_git_snapshot(
                repository=repository,
                target_kind="working-tree",
                scope_paths=("tracked.txt",),
            )
            (repository / "staged.txt").write_text("staged two\n", encoding="utf-8")
            _git(repository, "add", "staged.txt")
            (repository / "unstaged.txt").write_text("unstaged two\n", encoding="utf-8")
            (repository / "untracked.txt").write_text("untracked two\n", encoding="utf-8")
            (repository / "ignored.txt").write_text("ignored two\n", encoding="utf-8")
            second = self.module.capture_git_snapshot(
                repository=repository,
                target_kind="working-tree",
                scope_paths=("tracked.txt",),
            )

            self.assertEqual(first.snapshot_id, second.snapshot_id)
            self.assertEqual(first.scope_paths, ("tracked.txt",))
            self.assertEqual(tuple(entry.path for entry in first.entries), ("tracked.txt",))
            self.assertEqual(first.uncommitted_paths, ("tracked.txt",))

    def test_submodule_gitlink_is_metadata_only_for_worktree_and_staged(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            child_root = root / "child-root"
            parent_root = root / "parent-root"
            child_root.mkdir()
            parent_root.mkdir()
            child = _create_repository(child_root)
            parent = _create_repository(parent_root)
            _git(
                parent,
                "-c",
                "protocol.file.allow=always",
                "submodule",
                "add",
                str(child),
                "dependency",
            )
            _git(parent, "commit", "-am", "add dependency")

            dependency = parent / "dependency"
            _git(dependency, "config", "user.email", "tests@example.invalid")
            _git(dependency, "config", "user.name", "Policy Tests")
            (dependency / "tracked.txt").write_text("updated\n", encoding="utf-8")
            _git(dependency, "add", "tracked.txt")
            _git(dependency, "commit", "-m", "update dependency")

            worktree = self.module.capture_git_snapshot(
                repository=parent,
                target_kind="working-tree",
            )
            _git(parent, "add", "dependency")
            staged = self.module.capture_git_snapshot(
                repository=parent,
                target_kind="staged",
            )

            for result in (worktree, staged):
                with self.subTest(target_kind=result.target_kind):
                    self.assertEqual(result.changed_files, 1)
                    self.assertEqual(result.changed_lines, 0)
                    self.assertEqual(result.unavailable_patches, 1)
                    self.assertEqual(result.metadata_only_paths, ("dependency",))
                    self.assertFalse(result.local_evidence_complete)
                    self.assertEqual(result.entries[0].material, "submodule")
                    self.assertIsNone(result.entries[0].changed_lines)
                    self.assertEqual(result.entries[0].coverage, "metadata-only")

    def test_gitlink_probe_treats_changed_path_as_literal(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            child_root = root / "child-root"
            parent_root = root / "parent-root"
            child_root.mkdir()
            parent_root.mkdir()
            child = _create_repository(child_root)
            parent = _create_repository(parent_root)
            _git(
                parent,
                "-c",
                "protocol.file.allow=always",
                "submodule",
                "add",
                str(child),
                "fooa",
            )
            literal = parent / "foo[a]"
            literal.write_text("before\n", encoding="utf-8")
            _git(parent, "add", "foo[a]")
            _git(parent, "commit", "-am", "add literal file and submodule")
            literal.write_text("after\n", encoding="utf-8")

            result = self.module.capture_git_snapshot(
                repository=parent,
                target_kind="working-tree",
            )

            self.assertEqual(result.changed_files, 1)
            self.assertEqual(result.changed_lines, 2)
            self.assertEqual(result.unavailable_patches, 0)
            self.assertEqual(result.entries[0].path, "foo[a]")
            self.assertEqual(result.entries[0].material, "text")
            self.assertEqual(result.entries[0].coverage, "local-lines")

    def test_mode_only_change_is_disclosed_as_metadata_only(self):
        with tempfile.TemporaryDirectory() as temp:
            repository = _create_repository(Path(temp))
            _git(repository, "config", "core.filemode", "true")
            _git(repository, "update-index", "--chmod=+x", "tracked.txt")

            staged = self.module.capture_git_snapshot(
                repository=repository,
                target_kind="staged",
            )
            worktree = self.module.capture_git_snapshot(
                repository=repository,
                target_kind="working-tree",
            )

            for result in (staged, worktree):
                with self.subTest(target_kind=result.target_kind):
                    self.assertEqual(result.changed_files, 1)
                    self.assertEqual(result.changed_lines, 0)
                    self.assertEqual(result.unavailable_patches, 1)
                    self.assertFalse(result.local_evidence_complete)
                    self.assertEqual(result.entries[0].material, "mode-change")
                    self.assertEqual(result.entries[0].old_mode, "100644")
                    self.assertEqual(result.entries[0].new_mode, "100755")
                    self.assertEqual(result.entries[0].coverage, "metadata-only")

    def test_pure_rename_is_one_metadata_only_entry(self):
        with tempfile.TemporaryDirectory() as temp:
            repository = _create_repository(Path(temp))
            _git(repository, "mv", "tracked.txt", "renamed.txt")

            worktree = self.module.capture_git_snapshot(
                repository=repository,
                target_kind="working-tree",
            )
            staged = self.module.capture_git_snapshot(
                repository=repository,
                target_kind="staged",
            )

            for result in (worktree, staged):
                with self.subTest(target_kind=result.target_kind):
                    self.assertEqual(result.changed_files, 1)
                    self.assertEqual(result.changed_lines, 0)
                    self.assertEqual(result.unavailable_patches, 1)
                    self.assertEqual(result.metadata_only_paths, ("renamed.txt",))
                    self.assertFalse(result.local_evidence_complete)
                    self.assertTrue(result.entries[0].status.startswith("R"))
                    self.assertEqual(result.entries[0].path, "renamed.txt")
                    self.assertEqual(result.entries[0].source_path, "tracked.txt")
                    self.assertEqual(result.entries[0].material, "rename")

    def test_scoped_rename_preserves_cross_scope_relationship(self):
        with tempfile.TemporaryDirectory() as temp:
            repository = _create_repository(Path(temp))
            _git(repository, "mv", "tracked.txt", "renamed.txt")

            for target_kind in ("staged", "working-tree"):
                for scope in ("renamed.txt", "tracked.txt"):
                    with self.subTest(target_kind=target_kind, scope=scope):
                        result = self.module.capture_git_snapshot(
                            repository=repository,
                            target_kind=target_kind,
                            scope_paths=(scope,),
                        )
                        self.assertEqual(result.changed_files, 1)
                        self.assertEqual(result.changed_lines, 0)
                        self.assertEqual(result.unavailable_patches, 1)
                        self.assertTrue(result.entries[0].status.startswith("R"))
                        self.assertEqual(result.entries[0].path, "renamed.txt")
                        self.assertEqual(result.entries[0].source_path, "tracked.txt")
                        self.assertEqual(result.entries[0].material, "rename")
                        self.assertEqual(result.entries[0].coverage, "metadata-only")

    def test_source_scoped_committed_rename_keeps_destination_gap(self):
        with tempfile.TemporaryDirectory() as temp:
            repository = _create_repository(Path(temp))
            original = "".join(f"line {index}\n" for index in range(20))
            tracked = repository / "tracked.txt"
            tracked.write_text(original, encoding="utf-8")
            _git(repository, "add", "tracked.txt")
            _git(repository, "commit", "-m", "expand tracked file")
            base_sha = _git(repository, "rev-parse", "HEAD").stdout.strip()
            _git(repository, "mv", "tracked.txt", "renamed.txt")
            _git(repository, "commit", "-m", "rename tracked file")
            renamed = repository / "renamed.txt"
            renamed.write_text(original + "local change\n", encoding="utf-8")
            _git(repository, "add", "renamed.txt")

            first_snapshots = {}
            for target_kind in ("staged", "working-tree"):
                with self.subTest(target_kind=target_kind):
                    result = self.module.capture_git_snapshot(
                        repository=repository,
                        target_kind=target_kind,
                        base=base_sha,
                        scope_paths=("tracked.txt",),
                    )
                    self.assertEqual(result.changed_files, 1)
                    self.assertTrue(result.entries[0].status.startswith("R"))
                    self.assertEqual(result.entries[0].path, "renamed.txt")
                    self.assertEqual(result.entries[0].source_path, "tracked.txt")
                    self.assertTrue(result.entries[0].uncommitted)
                    self.assertEqual(result.uncommitted_paths, ("renamed.txt",))
                    self.assertEqual(result.permalink_gap_paths, ("renamed.txt",))
                    self.assertEqual(result.permalink_gap_files, 1)
                    first_snapshots[target_kind] = result

            renamed.write_text(original + "other change\n", encoding="utf-8")
            _git(repository, "add", "renamed.txt")
            for target_kind in ("staged", "working-tree"):
                with self.subTest(target_kind=target_kind, changed_content=True):
                    result = self.module.capture_git_snapshot(
                        repository=repository,
                        target_kind=target_kind,
                        base=base_sha,
                        scope_paths=("tracked.txt",),
                    )
                    self.assertNotEqual(
                        first_snapshots[target_kind].snapshot_id,
                        result.snapshot_id,
                    )

    def test_pure_copy_is_one_metadata_only_relationship(self):
        with tempfile.TemporaryDirectory() as temp:
            repository = _create_repository(Path(temp))
            (repository / "copied.txt").write_text("before\n", encoding="utf-8")
            _git(repository, "add", "copied.txt")

            staged = self.module.capture_git_snapshot(
                repository=repository,
                target_kind="staged",
            )
            worktree = self.module.capture_git_snapshot(
                repository=repository,
                target_kind="working-tree",
            )

            for result in (staged, worktree):
                with self.subTest(target_kind=result.target_kind):
                    self.assertEqual(result.changed_files, 1)
                    self.assertEqual(result.changed_lines, 0)
                    self.assertEqual(result.unavailable_patches, 1)
                    self.assertTrue(result.entries[0].status.startswith("C"))
                    self.assertEqual(result.entries[0].source_path, "tracked.txt")
                    self.assertEqual(result.entries[0].path, "copied.txt")
                    self.assertEqual(result.entries[0].material, "copy")

    def test_scoped_copy_preserves_source_relationship(self):
        with tempfile.TemporaryDirectory() as temp:
            repository = _create_repository(Path(temp))
            (repository / "copied.txt").write_text("before\n", encoding="utf-8")
            _git(repository, "add", "copied.txt")

            for target_kind in ("staged", "working-tree"):
                for scope in ("copied.txt", "tracked.txt"):
                    with self.subTest(target_kind=target_kind, scope=scope):
                        result = self.module.capture_git_snapshot(
                            repository=repository,
                            target_kind=target_kind,
                            scope_paths=(scope,),
                        )
                        self.assertEqual(result.changed_files, 1)
                        self.assertEqual(result.changed_lines, 0)
                        self.assertEqual(result.unavailable_patches, 1)
                        self.assertTrue(result.entries[0].status.startswith("C"))
                        self.assertEqual(result.entries[0].path, "copied.txt")
                        self.assertEqual(result.entries[0].source_path, "tracked.txt")
                        self.assertEqual(result.entries[0].material, "copy")
                        self.assertEqual(result.entries[0].coverage, "metadata-only")
                        self.assertTrue(result.entries[0].uncommitted)
                        self.assertEqual(result.uncommitted_paths, ("copied.txt",))
                        self.assertEqual(result.permalink_gap_paths, ("copied.txt",))
                        self.assertEqual(result.permalink_gap_files, 1)

    def test_committed_copy_scoped_to_source_has_no_permalink_gap(self):
        with tempfile.TemporaryDirectory() as temp:
            repository = _create_repository(Path(temp))
            base_sha = _git(repository, "rev-parse", "HEAD").stdout.strip()
            (repository / "copied.txt").write_text("before\n", encoding="utf-8")
            _git(repository, "add", "copied.txt")
            _git(repository, "commit", "-m", "copy tracked file")

            for target_kind in ("staged", "working-tree"):
                with self.subTest(target_kind=target_kind):
                    result = self.module.capture_git_snapshot(
                        repository=repository,
                        target_kind=target_kind,
                        base=base_sha,
                        scope_paths=("tracked.txt",),
                    )
                    self.assertEqual(result.changed_files, 1)
                    self.assertTrue(result.entries[0].status.startswith("C"))
                    self.assertEqual(result.entries[0].path, "copied.txt")
                    self.assertEqual(result.entries[0].source_path, "tracked.txt")
                    self.assertFalse(result.entries[0].uncommitted)
                    self.assertEqual(result.uncommitted_paths, ())
                    self.assertEqual(result.permalink_gap_paths, ())
                    self.assertEqual(result.permalink_gap_files, 0)

    def test_lfs_pointer_is_metadata_only_without_reading_lfs_object(self):
        with tempfile.TemporaryDirectory() as temp:
            repository = _create_repository(Path(temp))
            (repository / ".gitattributes").write_text(
                "*.dat filter=lfs\n",
                encoding="utf-8",
            )
            asset = repository / "asset.dat"
            asset.write_text(
                "version https://git-lfs.github.com/spec/v1\n"
                f"oid sha256:{'a' * 64}\n"
                "size 1\n",
                encoding="utf-8",
            )
            _git(repository, "add", ".gitattributes", "asset.dat")
            _git(repository, "commit", "-m", "add lfs pointer")
            asset.write_text(
                "version https://git-lfs.github.com/spec/v1\n"
                f"oid sha256:{'b' * 64}\n"
                "size 2\n",
                encoding="utf-8",
            )

            with mock.patch.object(
                Path,
                "read_bytes",
                side_effect=AssertionError("LFS object content must not be read directly"),
            ):
                worktree = self.module.capture_git_snapshot(
                    repository=repository,
                    target_kind="working-tree",
                )
            _git(repository, "add", "asset.dat")
            staged = self.module.capture_git_snapshot(
                repository=repository,
                target_kind="staged",
            )

            for result in (worktree, staged):
                with self.subTest(target_kind=result.target_kind):
                    self.assertEqual(result.changed_files, 1)
                    self.assertEqual(result.changed_lines, 4)
                    self.assertEqual(result.unavailable_patches, 1)
                    self.assertFalse(result.local_evidence_complete)
                    self.assertEqual(result.entries[0].material, "lfs-pointer")
                    self.assertEqual(result.entries[0].coverage, "metadata-only")

    def test_lfs_attribute_probe_errors_fail_closed(self):
        with tempfile.TemporaryDirectory() as temp:
            repository = _create_repository(Path(temp))
            (repository / "tracked.txt").write_text("modified\n", encoding="utf-8")
            original_run_git = self.module._run_git

            for failed_probe in ("current", "base"):
                with self.subTest(failed_probe=failed_probe):
                    def fail_probe(repo, *args):
                        is_attr = bool(args) and args[0] == "check-attr"
                        is_base = any(arg.startswith("--source=") for arg in args)
                        should_fail = is_attr and (
                            (failed_probe == "base" and is_base)
                            or (failed_probe == "current" and not is_base)
                        )
                        if should_fail:
                            return subprocess.CompletedProcess(
                                ["git", *args],
                                1,
                                stdout=b"",
                                stderr=b"attribute probe failed",
                            )
                        return original_run_git(repo, *args)

                    with mock.patch.object(
                        self.module,
                        "_run_git",
                        side_effect=fail_probe,
                    ):
                        with self.assertRaisesRegex(RuntimeError, "attribute probe failed"):
                            self.module.capture_git_snapshot(
                                repository=repository,
                                target_kind="working-tree",
                            )

    def test_scoped_snapshot_identity_binds_tracked_lfs_classification(self):
        with tempfile.TemporaryDirectory() as temp:
            repository = _create_repository(Path(temp))
            asset = repository / "asset.dat"
            asset.write_text("before\n", encoding="utf-8")
            _git(repository, "add", "asset.dat")
            _git(repository, "commit", "-m", "add ordinary asset")
            asset.write_text("after\n", encoding="utf-8")
            _git(repository, "add", "asset.dat")

            ordinary = self.module.capture_git_snapshot(
                repository=repository,
                target_kind="staged",
                scope_paths=("asset.dat",),
            )
            (repository / ".gitattributes").write_text(
                "*.dat filter=lfs\n",
                encoding="utf-8",
            )
            _git(repository, "add", ".gitattributes")
            lfs_classified = self.module.capture_git_snapshot(
                repository=repository,
                target_kind="staged",
                scope_paths=("asset.dat",),
            )

            self.assertEqual(ordinary.entries[0].material, "text")
            self.assertTrue(ordinary.local_evidence_complete)
            self.assertEqual(lfs_classified.entries[0].material, "lfs-pointer")
            self.assertFalse(lfs_classified.local_evidence_complete)
            self.assertNotEqual(ordinary.snapshot_id, lfs_classified.snapshot_id)

    def test_untracked_lfs_object_is_metadata_only_without_content_read(self):
        with tempfile.TemporaryDirectory() as temp:
            repository = _create_repository(Path(temp))
            (repository / ".gitattributes").write_text(
                "*.dat filter=lfs\n",
                encoding="utf-8",
            )
            _git(repository, "add", ".gitattributes")
            _git(repository, "commit", "-m", "configure lfs")
            asset = repository / "untracked.dat"
            asset.write_bytes(b"local-lfs-object")

            with mock.patch.object(
                Path,
                "read_bytes",
                side_effect=AssertionError("untracked LFS object must not be read"),
            ):
                result = self.module.capture_git_snapshot(
                    repository=repository,
                    target_kind="working-tree",
                )

            self.assertEqual(result.changed_files, 1)
            self.assertEqual(result.unavailable_patches, 1)
            self.assertFalse(result.local_evidence_complete)
            self.assertEqual(result.entries[0].material, "lfs-pointer")
            self.assertEqual(result.entries[0].content_bytes, len(b"local-lfs-object"))

    def test_untracked_nested_repository_is_disclosed_as_metadata_only(self):
        with tempfile.TemporaryDirectory() as temp:
            repository = _create_repository(Path(temp))
            nested = repository / "vendor"
            nested.mkdir()
            _git(nested, "init")
            _git(nested, "config", "user.email", "tests@example.invalid")
            _git(nested, "config", "user.name", "Policy Tests")
            (nested / "nested.txt").write_text("nested\n", encoding="utf-8")
            _git(nested, "add", "nested.txt")
            _git(nested, "commit", "-m", "nested repository")

            result = self.module.capture_git_snapshot(
                repository=repository,
                target_kind="working-tree",
            )

            self.assertEqual(result.changed_files, 1)
            self.assertEqual(result.changed_lines, 0)
            self.assertEqual(result.unavailable_patches, 1)
            self.assertFalse(result.local_evidence_complete)
            self.assertEqual(result.entries[0].path.rstrip("/"), "vendor")
            self.assertEqual(result.entries[0].material, "untracked-directory")
            self.assertEqual(result.entries[0].coverage, "metadata-only")

    def test_patch_capture_does_not_buffer_binary_diff_through_git_helper(self):
        with tempfile.TemporaryDirectory() as temp:
            repository = _create_repository(Path(temp))
            (repository / "tracked.txt").write_text("modified\n", encoding="utf-8")
            original_git = self.module._git

            def reject_buffered_patch(repo, *args, **kwargs):
                if "--binary" in args:
                    raise AssertionError("binary patch must use streaming capture")
                return original_git(repo, *args, **kwargs)

            with mock.patch.object(
                self.module,
                "_git",
                side_effect=reject_buffered_patch,
            ):
                result = self.module.capture_git_snapshot(
                    repository=repository,
                    target_kind="working-tree",
                )

            self.assertEqual(result.changed_files, 1)
            self.assertGreater(result.patch_bytes, 0)

    def test_index_deleted_path_recreated_untracked_is_counted_once(self):
        with tempfile.TemporaryDirectory() as temp:
            repository = _create_repository(Path(temp))
            _git(repository, "rm", "--cached", "tracked.txt")

            result = self.module.capture_git_snapshot(
                repository=repository,
                target_kind="working-tree",
            )

            self.assertEqual(result.changed_files, 1)
            self.assertEqual(tuple(entry.path for entry in result.entries), ("tracked.txt",))
            self.assertEqual(result.changed_lines, 0)
            self.assertEqual(result.unavailable_patches, 1)
            self.assertEqual(result.entries[0].material, "untracked-replacement")
            self.assertEqual(result.entries[0].coverage, "metadata-only")

    def test_lockfile_is_metadata_only(self):
        with tempfile.TemporaryDirectory() as temp:
            repository = _create_repository(Path(temp))
            lockfile = repository / "package-lock.json"
            lockfile.write_text('{"lockfileVersion": 1}\n', encoding="utf-8")
            _git(repository, "add", "package-lock.json")
            _git(repository, "commit", "-m", "add lockfile")
            lockfile.write_text('{"lockfileVersion": 2}\n', encoding="utf-8")

            result = self.module.capture_git_snapshot(
                repository=repository,
                target_kind="working-tree",
            )

            self.assertEqual(result.changed_files, 1)
            self.assertEqual(result.changed_lines, 2)
            self.assertEqual(result.unavailable_patches, 1)
            self.assertEqual(result.entries[0].material, "lockfile")
            self.assertEqual(result.entries[0].coverage, "metadata-only")

    def test_standard_lockfile_matrix_is_metadata_only(self):
        lockfiles = (
            "npm-shrinkwrap.json",
            "go.sum",
            "go.work.sum",
            "Package.resolved",
            "bun.lockb",
            "gradle.lockfile",
        )
        for name in lockfiles:
            with self.subTest(name=name), tempfile.TemporaryDirectory() as temp:
                repository = _create_repository(Path(temp))
                path = repository / name
                path.write_text("before\n", encoding="utf-8")
                _git(repository, "add", name)
                _git(repository, "commit", "-m", "add lockfile")
                path.write_text("after\n", encoding="utf-8")

                result = self.module.capture_git_snapshot(
                    repository=repository,
                    target_kind="working-tree",
                )

                entry = next(item for item in result.entries if item.path == name)
                self.assertEqual(entry.material, "lockfile")
                self.assertEqual(entry.coverage, "metadata-only")

    def test_non_lock_manifests_remain_text(self):
        for name in ("package.json", "go.mod"):
            with self.subTest(name=name), tempfile.TemporaryDirectory() as temp:
                repository = _create_repository(Path(temp))
                path = repository / name
                path.write_text("before\n", encoding="utf-8")
                _git(repository, "add", name)
                _git(repository, "commit", "-m", "add manifest")
                path.write_text("after\n", encoding="utf-8")

                result = self.module.capture_git_snapshot(
                    repository=repository,
                    target_kind="working-tree",
                )

                entry = next(item for item in result.entries if item.path == name)
                self.assertEqual(entry.material, "text")

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

    def test_tracked_path_cannot_be_readded_as_explicit_ignored_material(self):
        with tempfile.TemporaryDirectory() as temp:
            repository = _create_repository(Path(temp))
            (repository / ".gitignore").write_text("*.txt\n", encoding="utf-8")
            _git(repository, "add", ".gitignore")
            _git(repository, "commit", "-m", "ignore text files")
            (repository / "tracked.txt").write_text("modified\n", encoding="utf-8")

            with self.assertRaisesRegex(ValueError, "tracked"):
                self.module.capture_git_snapshot(
                    repository=repository,
                    target_kind="working-tree",
                    included_ignored_paths=("tracked.txt",),
                )

    def test_explicit_ignored_path_with_pathspec_metacharacters_is_literal(self):
        with tempfile.TemporaryDirectory() as temp:
            repository = _create_repository(Path(temp))
            (repository / "fooa").write_text("tracked sibling\n", encoding="utf-8")
            _git(repository, "add", "fooa")
            _git(repository, "commit", "-m", "add tracked sibling")
            (repository / ".gitignore").write_text(
                "foo*\n",
                encoding="utf-8",
            )
            _git(repository, "add", ".gitignore")
            _git(repository, "commit", "-m", "add pathspec fixtures")
            (repository / "foo[a]").write_text("ignored literal\n", encoding="utf-8")

            result = self.module.capture_git_snapshot(
                repository=repository,
                target_kind="working-tree",
                included_ignored_paths=("foo[a]",),
            )

            self.assertEqual(result.changed_files, 1)
            self.assertEqual(result.included_ignored_paths, ("foo[a]",))
            self.assertEqual(result.entries[0].path, "foo[a]")
            self.assertEqual(result.entries[0].status, "!")

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
