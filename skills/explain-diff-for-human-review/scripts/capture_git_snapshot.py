#!/usr/bin/env python3
"""Capture privacy-preserving metadata for a staged or working-tree snapshot."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
from dataclasses import asdict, dataclass
from pathlib import Path, PurePosixPath
from typing import Iterable


TARGET_KINDS = frozenset({"staged", "working-tree"})
@dataclass(frozen=True)
class SnapshotEntry:
    path: str
    status: str
    material: str
    changed_lines: int | None
    content_bytes: int
    uncommitted: bool
    coverage: str
    omission_reason: str | None


@dataclass(frozen=True)
class GitSnapshot:
    schema_version: int
    target_kind: str
    base_sha: str
    head_sha: str
    snapshot_id: str
    changed_files: int
    changed_lines: int
    patch_bytes: int
    unavailable_patches: int
    local_evidence_complete: bool
    uncommitted_paths: tuple[str, ...]
    permalink_gap_paths: tuple[str, ...]
    permalink_gap_files: int
    metadata_only_paths: tuple[str, ...]
    generated_paths: tuple[str, ...]
    included_ignored_paths: tuple[str, ...]
    ignored_policy: str
    entries: tuple[SnapshotEntry, ...]


@dataclass(frozen=True)
class _CapturedMaterial:
    patch: bytes
    name_status: tuple[tuple[str, str], ...]
    numstat: tuple[tuple[str, int | None], ...]
    untracked: tuple[tuple[str, bytes], ...]
    included_ignored_paths: tuple[str, ...]
    uncommitted_paths: tuple[str, ...]


def _git(repository: Path, *args: str, check: bool = True) -> bytes:
    completed = subprocess.run(
        ["git", "-C", str(repository), *args],
        check=False,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    if check and completed.returncode != 0:
        message = completed.stderr.decode("utf-8", errors="replace").strip()
        raise RuntimeError(f"git {' '.join(args)} failed: {message}")
    return completed.stdout


def _decode_path(value: bytes) -> str:
    return value.decode("utf-8", errors="surrogateescape")


def _parse_name_status(payload: bytes) -> tuple[tuple[str, str], ...]:
    tokens = [token for token in payload.split(b"\0") if token]
    if len(tokens) % 2:
        raise RuntimeError("unexpected git name-status output")
    return tuple(
        (tokens[index].decode("ascii", errors="replace"), _decode_path(tokens[index + 1]))
        for index in range(0, len(tokens), 2)
    )


def _parse_numstat(payload: bytes) -> tuple[tuple[str, int | None], ...]:
    rows: list[tuple[str, int | None]] = []
    for record in payload.split(b"\0"):
        if not record:
            continue
        fields = record.split(b"\t", 2)
        if len(fields) != 3:
            raise RuntimeError("unexpected git numstat output")
        added, deleted, raw_path = fields
        changed_lines = None
        if added != b"-" and deleted != b"-":
            changed_lines = int(added) + int(deleted)
        rows.append((_decode_path(raw_path), changed_lines))
    return tuple(rows)


def _diff_arguments(target_kind: str, base_sha: str, *options: str) -> list[str]:
    args = ["diff", *options, "--no-renames"]
    if target_kind == "staged":
        args.append("--cached")
    args.extend([base_sha, "--"])
    return args


def _uncommitted_arguments(target_kind: str, head_sha: str) -> list[str]:
    args = ["diff", "--name-only", "-z", "--no-renames"]
    if target_kind == "staged":
        args.append("--cached")
    args.extend([head_sha, "--"])
    return args


def _read_untracked(repository: Path) -> tuple[tuple[str, bytes], ...]:
    payload = _git(repository, "ls-files", "--others", "--exclude-standard", "-z")
    items: list[tuple[str, bytes]] = []
    for raw_path in payload.split(b"\0"):
        if not raw_path:
            continue
        path = _decode_path(raw_path)
        absolute = repository / Path(path)
        if absolute.is_symlink():
            data = os.readlink(absolute).encode("utf-8", errors="surrogateescape")
        elif absolute.is_file():
            data = absolute.read_bytes()
        else:
            raise RuntimeError(f"untracked path changed while capturing snapshot: {path}")
        items.append((path, data))
    return tuple(sorted(items))


def _read_explicit_ignored(
    repository: Path,
    paths: frozenset[str],
) -> tuple[tuple[str, bytes], ...]:
    items: list[tuple[str, bytes]] = []
    for path in sorted(paths):
        ignored = _git(
            repository,
            "check-ignore",
            "--no-index",
            "--",
            path,
            check=False,
        )
        if not ignored:
            raise ValueError(f"explicit ignored path is not ignored by Git: {path}")
        absolute = repository / Path(path)
        if absolute.is_symlink():
            data = os.readlink(absolute).encode("utf-8", errors="surrogateescape")
        elif absolute.is_file():
            data = absolute.read_bytes()
        else:
            raise ValueError(f"explicit ignored path is not a file: {path}")
        items.append((path, data))
    return tuple(items)


def _capture_material(
    repository: Path,
    target_kind: str,
    base_sha: str,
    head_sha: str,
    included_ignored_paths: frozenset[str],
) -> _CapturedMaterial:
    patch = _git(
        repository,
        *_diff_arguments(
            target_kind,
            base_sha,
            "--binary",
            "--full-index",
            "--no-ext-diff",
            "--no-textconv",
        ),
    )
    name_status = _parse_name_status(
        _git(
            repository,
            *_diff_arguments(target_kind, base_sha, "--name-status", "-z"),
        )
    )
    numstat = _parse_numstat(
        _git(
            repository,
            *_diff_arguments(target_kind, base_sha, "--numstat", "-z"),
        )
    )
    untracked = ()
    if target_kind == "working-tree":
        untracked = tuple(sorted(
            (
                *_read_untracked(repository),
                *_read_explicit_ignored(repository, included_ignored_paths),
            )
        ))

    uncommitted = {
        _decode_path(path)
        for path in _git(
            repository,
            *_uncommitted_arguments(target_kind, head_sha),
        ).split(b"\0")
        if path
    }
    uncommitted.update(path for path, _ in untracked)
    return _CapturedMaterial(
        patch=patch,
        name_status=name_status,
        numstat=numstat,
        untracked=untracked,
        included_ignored_paths=tuple(sorted(included_ignored_paths)),
        uncommitted_paths=tuple(sorted(uncommitted)),
    )


def _fingerprint(
    *,
    target_kind: str,
    base_sha: str,
    head_sha: str,
    material: _CapturedMaterial,
    generated_paths: frozenset[str],
) -> str:
    digest = hashlib.sha256()

    def add(value: bytes) -> None:
        digest.update(len(value).to_bytes(8, "big"))
        digest.update(value)

    for value in (
        b"explain-diff-local-snapshot-v1",
        target_kind.encode("ascii"),
        base_sha.encode("ascii"),
        head_sha.encode("ascii"),
        material.patch,
    ):
        add(value)
    for path, content in material.untracked:
        add(path.encode("utf-8", errors="surrogateescape"))
        add(content)
    for path in material.included_ignored_paths:
        add(b"ignored")
        add(path.encode("utf-8", errors="surrogateescape"))
    for path in sorted(generated_paths):
        add(b"generated")
        add(path.encode("utf-8", errors="surrogateescape"))
    return f"sha256:{digest.hexdigest()}"


def _normalize_paths(paths: Iterable[str], *, label: str) -> frozenset[str]:
    normalized: set[str] = set()
    for value in paths:
        path = PurePosixPath(value.replace("\\", "/"))
        if (
            path.is_absolute()
            or ".." in path.parts
            or str(path) in {"", "."}
            or (path.parts and ":" in path.parts[0])
        ):
            raise ValueError(f"{label} must be repository-relative: {value}")
        normalized.add(str(path))
    return frozenset(normalized)


def _is_text(content: bytes) -> bool:
    if b"\0" in content:
        return False
    try:
        content.decode("utf-8")
    except UnicodeDecodeError:
        return False
    return True


def _line_count(content: bytes) -> int:
    if not content:
        return 0
    return content.count(b"\n") + (0 if content.endswith(b"\n") else 1)


def _tracked_content(repository: Path, target_kind: str, path: str) -> bytes:
    if target_kind == "staged":
        return _git(repository, "show", f":{path}", check=False)
    absolute = repository / Path(path)
    if absolute.is_symlink():
        return os.readlink(absolute).encode("utf-8", errors="surrogateescape")
    if absolute.is_file():
        return absolute.read_bytes()
    return b""


def _is_gitlink(repository: Path, base_sha: str, path: str) -> bool:
    current = _git(repository, "ls-files", "--stage", "-z", "--", path)
    base = _git(repository, "ls-tree", "-z", base_sha, "--", path)
    return any(
        record.startswith(b"160000 ")
        for payload in (current, base)
        for record in payload.split(b"\0")
        if record
    )


def capture_git_snapshot(
    *,
    repository: str | Path,
    target_kind: str,
    base: str = "HEAD",
    generated_paths: Iterable[str] = (),
    included_ignored_paths: Iterable[str] = (),
) -> GitSnapshot:
    """Return stable metadata for a local mutable target without returning source."""

    normalized_target = target_kind.strip().lower()
    if normalized_target not in TARGET_KINDS:
        raise ValueError(
            "target_kind must be one of: " + ", ".join(sorted(TARGET_KINDS))
        )
    requested = Path(repository).resolve()
    root_output = _git(requested, "rev-parse", "--show-toplevel")
    root = Path(root_output.decode("utf-8", errors="surrogateescape").strip()).resolve()
    base_sha = _git(root, "rev-parse", "--verify", f"{base}^{{commit}}").decode().strip()
    head_sha = _git(root, "rev-parse", "--verify", "HEAD^{commit}").decode().strip()
    generated = _normalize_paths(generated_paths, label="generated path")
    included_ignored = _normalize_paths(
        included_ignored_paths,
        label="ignored path",
    )
    if normalized_target == "staged" and included_ignored:
        raise ValueError("staged target cannot include ignored worktree paths")

    first = _capture_material(
        root,
        normalized_target,
        base_sha,
        head_sha,
        included_ignored,
    )
    second = _capture_material(
        root,
        normalized_target,
        base_sha,
        head_sha,
        included_ignored,
    )
    if first != second:
        raise RuntimeError("local target changed while capturing snapshot; retry")

    target_paths = {path for _, path in second.name_status}
    target_paths.update(path for path, _ in second.untracked)
    generated = frozenset(generated.intersection(target_paths))
    stats = dict(second.numstat)
    uncommitted = frozenset(second.uncommitted_paths)
    entries: list[SnapshotEntry] = []
    metadata_only: list[str] = []
    unavailable_patches = 0

    for status, path in second.name_status:
        content = _tracked_content(root, normalized_target, path)
        changed_lines = stats.get(path)
        if _is_gitlink(root, base_sha, path):
            material = "submodule"
            changed_lines = None
        elif path in generated:
            material = "generated"
        else:
            material = "text" if changed_lines is not None else "binary"
        omission_reason = None
        coverage = "local-lines" if path in uncommitted else "immutable-head"
        if material != "text":
            unavailable_patches += 1
            metadata_only.append(path)
            coverage = "metadata-only"
            omission_reason = f"{material} material is not line-reviewed"
        entries.append(
            SnapshotEntry(
                path=path,
                status=status,
                material=material,
                changed_lines=changed_lines,
                content_bytes=len(content),
                uncommitted=path in uncommitted,
                coverage=coverage,
                omission_reason=omission_reason,
            )
        )

    for path, content in second.untracked:
        is_generated = path in generated
        is_text = _is_text(content)
        material = "generated" if is_generated else ("text" if is_text else "binary")
        changed_lines = _line_count(content) if is_text else None
        omission_reason = None
        coverage = "local-lines"
        if material != "text":
            unavailable_patches += 1
            metadata_only.append(path)
            coverage = "metadata-only"
            omission_reason = f"{material} material is not line-reviewed"
        entries.append(
            SnapshotEntry(
                path=path,
                status="!" if path in included_ignored else "?",
                material=material,
                changed_lines=changed_lines,
                content_bytes=len(content),
                uncommitted=True,
                coverage=coverage,
                omission_reason=omission_reason,
            )
        )

    entries.sort(key=lambda item: item.path)
    changed_lines_total = sum(entry.changed_lines or 0 for entry in entries)
    patch_bytes = len(second.patch) + sum(
        len(content) for _, content in second.untracked
    )
    final = _capture_material(
        root,
        normalized_target,
        base_sha,
        head_sha,
        included_ignored,
    )
    if second != final:
        raise RuntimeError("local target changed while capturing snapshot; retry")
    snapshot_id = _fingerprint(
        target_kind=normalized_target,
        base_sha=base_sha,
        head_sha=head_sha,
        material=second,
        generated_paths=generated,
    )
    return GitSnapshot(
        schema_version=1,
        target_kind=normalized_target,
        base_sha=base_sha,
        head_sha=head_sha,
        snapshot_id=snapshot_id,
        changed_files=len(entries),
        changed_lines=changed_lines_total,
        patch_bytes=patch_bytes,
        unavailable_patches=unavailable_patches,
        local_evidence_complete=unavailable_patches == 0,
        uncommitted_paths=second.uncommitted_paths,
        permalink_gap_paths=second.uncommitted_paths,
        permalink_gap_files=len(second.uncommitted_paths),
        metadata_only_paths=tuple(sorted(metadata_only)),
        generated_paths=tuple(sorted(generated)),
        included_ignored_paths=second.included_ignored_paths,
        ignored_policy="excluded-unless-explicitly-scoped",
        entries=tuple(entries),
    )


def snapshot_to_json(snapshot: GitSnapshot) -> str:
    return json.dumps(asdict(snapshot), ensure_ascii=True, sort_keys=True)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repository", default=".")
    parser.add_argument("--target-kind", required=True, choices=sorted(TARGET_KINDS))
    parser.add_argument("--base", default="HEAD")
    parser.add_argument(
        "--generated-path",
        action="append",
        default=[],
        help="repository-relative generated/vendor path; repeat as needed",
    )
    parser.add_argument(
        "--include-ignored-path",
        action="append",
        default=[],
        help="explicit repository-relative ignored file; repeat as needed",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    snapshot = capture_git_snapshot(
        repository=args.repository,
        target_kind=args.target_kind,
        base=args.base,
        generated_paths=args.generated_path,
        included_ignored_paths=args.include_ignored_path,
    )
    print(snapshot_to_json(snapshot))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
