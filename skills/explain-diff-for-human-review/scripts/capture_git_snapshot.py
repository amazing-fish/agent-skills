#!/usr/bin/env python3
"""Capture privacy-preserving metadata for a staged or working-tree snapshot."""

from __future__ import annotations

import argparse
import codecs
import hashlib
import json
import os
import subprocess
import tempfile
from dataclasses import asdict, dataclass
from pathlib import Path, PurePosixPath
from typing import Iterable


TARGET_KINDS = frozenset({"staged", "working-tree"})
LOCKFILE_NAMES = frozenset({
    "bun.lockb",
    "cargo.lock",
    "composer.lock",
    "gemfile.lock",
    "go.sum",
    "go.work.sum",
    "gradle.lockfile",
    "npm-shrinkwrap.json",
    "package-lock.json",
    "package.resolved",
    "pipfile.lock",
    "pnpm-lock.yaml",
    "poetry.lock",
    "uv.lock",
    "yarn.lock",
})
@dataclass(frozen=True)
class SnapshotEntry:
    path: str
    status: str
    material: str
    changed_lines: int | None
    content_bytes: int | None
    uncommitted: bool
    coverage: str
    omission_reason: str | None
    source_path: str | None = None


@dataclass(frozen=True)
class GitSnapshot:
    schema_version: int
    target_kind: str
    scope_paths: tuple[str, ...]
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
class _UntrackedMaterial:
    path: str
    content_digest: str
    content_bytes: int | None
    changed_lines: int | None
    is_text: bool | None
    material_hint: str | None


@dataclass(frozen=True)
class _CapturedMaterial:
    patch_digest: str
    patch_bytes: int
    name_status: tuple[tuple[str, str, str | None], ...]
    numstat: tuple[tuple[str, int | None], ...]
    untracked: tuple[_UntrackedMaterial, ...]
    included_ignored_paths: tuple[str, ...]
    uncommitted_paths: tuple[str, ...]


def _run_git(repository: Path, *args: str) -> subprocess.CompletedProcess[bytes]:
    return subprocess.run(
        ["git", "-C", str(repository), *args],
        check=False,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )


def _run_git_with_input(
    repository: Path,
    input_bytes: bytes,
    *args: str,
) -> subprocess.CompletedProcess[bytes]:
    return subprocess.run(
        ["git", "-C", str(repository), *args],
        check=False,
        input=input_bytes,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )


def _git(repository: Path, *args: str, check: bool = True) -> bytes:
    completed = _run_git(repository, *args)
    if check and completed.returncode != 0:
        message = completed.stderr.decode("utf-8", errors="replace").strip()
        raise RuntimeError(f"git {' '.join(args)} failed: {message}")
    return completed.stdout


def _stream_git_digest(repository: Path, *args: str) -> tuple[str, int]:
    digest = hashlib.sha256()
    byte_count = 0
    with tempfile.TemporaryFile() as stderr:
        process = subprocess.Popen(
            ["git", "-C", str(repository), *args],
            stdout=subprocess.PIPE,
            stderr=stderr,
        )
        if process.stdout is None:
            raise RuntimeError("git patch stream is unavailable")
        with process.stdout:
            while chunk := process.stdout.read(64 * 1024):
                digest.update(chunk)
                byte_count += len(chunk)
        returncode = process.wait()
        if returncode != 0:
            stderr.seek(0)
            message = stderr.read().decode("utf-8", errors="replace").strip()
            raise RuntimeError(f"git {' '.join(args)} failed: {message}")
    return digest.hexdigest(), byte_count


def _decode_path(value: bytes) -> str:
    return value.decode("utf-8", errors="surrogateescape")


def _parse_name_status(payload: bytes) -> tuple[tuple[str, str, str | None], ...]:
    tokens = [token for token in payload.split(b"\0") if token]
    rows: list[tuple[str, str, str | None]] = []
    index = 0
    while index < len(tokens):
        status = tokens[index].decode("ascii", errors="replace")
        if status.startswith(("R", "C")):
            if index + 2 >= len(tokens):
                raise RuntimeError("unexpected git rename status output")
            source_path = _decode_path(tokens[index + 1])
            path = _decode_path(tokens[index + 2])
            index += 3
        else:
            if index + 1 >= len(tokens):
                raise RuntimeError("unexpected git name-status output")
            source_path = None
            path = _decode_path(tokens[index + 1])
            index += 2
        rows.append((status, path, source_path))
    return tuple(rows)


def _parse_numstat(payload: bytes) -> tuple[tuple[str, int | None], ...]:
    rows: list[tuple[str, int | None]] = []
    records = payload.split(b"\0")
    if records and not records[-1]:
        records.pop()
    index = 0
    while index < len(records):
        record = records[index]
        fields = record.split(b"\t", 2)
        if len(fields) != 3:
            raise RuntimeError("unexpected git numstat output")
        added, deleted, raw_path = fields
        if raw_path:
            path = _decode_path(raw_path)
            index += 1
        else:
            if index + 2 >= len(records):
                raise RuntimeError("unexpected git rename numstat output")
            path = _decode_path(records[index + 2])
            index += 3
        changed_lines = None
        if added != b"-" and deleted != b"-":
            changed_lines = int(added) + int(deleted)
        rows.append((path, changed_lines))
    return tuple(rows)


def _literal_pathspecs(paths: tuple[str, ...]) -> list[str]:
    return [f":(literal){path}" for path in paths]


def _diff_arguments(
    target_kind: str,
    base_sha: str,
    scope_paths: tuple[str, ...],
    *options: str,
) -> list[str]:
    args = ["diff", *options, "--find-renames", "--find-copies-harder"]
    if target_kind == "staged":
        args.append("--cached")
    args.extend([base_sha, "--", *_literal_pathspecs(scope_paths)])
    return args


def _uncommitted_arguments(
    target_kind: str,
    head_sha: str,
    scope_paths: tuple[str, ...],
) -> list[str]:
    args = ["diff", "--name-only", "-z", "--find-renames", "--find-copies-harder"]
    if target_kind == "staged":
        args.append("--cached")
    args.extend([head_sha, "--", *_literal_pathspecs(scope_paths)])
    return args


def _stream_file_material(path: Path) -> tuple[str, int, int | None, bool]:
    digest = hashlib.sha256()
    decoder = codecs.getincrementaldecoder("utf-8")()
    is_text = True
    byte_count = 0
    newline_count = 0
    last_byte = b""
    with path.open("rb") as stream:
        while chunk := stream.read(64 * 1024):
            digest.update(chunk)
            byte_count += len(chunk)
            newline_count += chunk.count(b"\n")
            last_byte = chunk[-1:]
            if b"\0" in chunk:
                is_text = False
            if is_text:
                try:
                    decoder.decode(chunk)
                except UnicodeDecodeError:
                    is_text = False
        if is_text:
            try:
                decoder.decode(b"", final=True)
            except UnicodeDecodeError:
                is_text = False
    changed_lines = None
    if is_text:
        changed_lines = newline_count + (
            1 if byte_count and last_byte != b"\n" else 0
        )
    return digest.hexdigest(), byte_count, changed_lines, is_text


def _metadata_digest(path: str, absolute: Path, material: str) -> str:
    stat = absolute.stat()
    payload = f"{material}\0{path}\0{stat.st_size}\0{stat.st_mtime_ns}".encode(
        "utf-8",
        errors="surrogateescape",
    )
    return hashlib.sha256(payload).hexdigest()


def _capture_untracked_path(
    repository: Path,
    target_kind: str,
    base_sha: str,
    path: str,
) -> _UntrackedMaterial:
    absolute = repository / Path(path)
    if absolute.is_symlink():
        content = os.readlink(absolute).encode("utf-8", errors="surrogateescape")
        is_text = _is_text(content)
        return _UntrackedMaterial(
            path=path,
            content_digest=hashlib.sha256(content).hexdigest(),
            content_bytes=len(content),
            changed_lines=_line_count(content) if is_text else None,
            is_text=is_text,
            material_hint=None,
        )
    if absolute.is_dir():
        return _UntrackedMaterial(
            path=path,
            content_digest=_metadata_digest(path, absolute, "untracked-directory"),
            content_bytes=None,
            changed_lines=None,
            is_text=None,
            material_hint="untracked-directory",
        )
    if not absolute.is_file():
        raise RuntimeError(f"untracked path changed while capturing snapshot: {path}")
    if _uses_lfs_filter(repository, target_kind, base_sha, path):
        return _UntrackedMaterial(
            path=path,
            content_digest=_metadata_digest(path, absolute, "lfs-pointer"),
            content_bytes=absolute.stat().st_size,
            changed_lines=None,
            is_text=None,
            material_hint="lfs-pointer",
        )
    content_digest, content_bytes, changed_lines, is_text = _stream_file_material(
        absolute
    )
    return _UntrackedMaterial(
        path=path,
        content_digest=content_digest,
        content_bytes=content_bytes,
        changed_lines=changed_lines,
        is_text=is_text,
        material_hint=None,
    )


def _read_untracked(
    repository: Path,
    target_kind: str,
    base_sha: str,
    scope_paths: tuple[str, ...],
) -> tuple[_UntrackedMaterial, ...]:
    payload = _git(
        repository,
        "ls-files",
        "--others",
        "--exclude-standard",
        "-z",
        "--",
        *_literal_pathspecs(scope_paths),
    )
    items: list[_UntrackedMaterial] = []
    for raw_path in payload.split(b"\0"):
        if not raw_path:
            continue
        path = _decode_path(raw_path)
        items.append(_capture_untracked_path(repository, target_kind, base_sha, path))
    return tuple(sorted(items, key=lambda item: item.path))


def _read_explicit_ignored(
    repository: Path,
    target_kind: str,
    base_sha: str,
    paths: frozenset[str],
) -> tuple[_UntrackedMaterial, ...]:
    items: list[_UntrackedMaterial] = []
    for path in sorted(paths):
        tracked = _git(
            repository,
            "ls-files",
            "-z",
            "--",
            *_literal_pathspecs((path,)),
        )
        if tracked:
            raise ValueError(f"explicit ignored path is tracked by Git: {path}")
        ignored_probe = _run_git_with_input(
            repository,
            path.encode("utf-8", errors="surrogateescape") + b"\0",
            "check-ignore",
            "--no-index",
            "--stdin",
            "-z",
        )
        if ignored_probe.returncode not in {0, 1}:
            message = ignored_probe.stderr.decode(
                "utf-8",
                errors="replace",
            ).strip()
            raise RuntimeError(
                f"git check-ignore --no-index --stdin -z failed: {message}"
            )
        ignored = ignored_probe.stdout
        if not ignored:
            raise ValueError(f"explicit ignored path is not ignored by Git: {path}")
        absolute = repository / Path(path)
        if not absolute.is_symlink() and not absolute.is_file():
            raise ValueError(f"explicit ignored path is not a file: {path}")
        items.append(_capture_untracked_path(repository, target_kind, base_sha, path))
    return tuple(items)


def _capture_material(
    repository: Path,
    target_kind: str,
    base_sha: str,
    head_sha: str,
    included_ignored_paths: frozenset[str],
    scope_paths: tuple[str, ...],
) -> _CapturedMaterial:
    patch_digest, patch_bytes = _stream_git_digest(
        repository,
        *_diff_arguments(
            target_kind,
            base_sha,
            scope_paths,
            "--binary",
            "--full-index",
            "--no-ext-diff",
            "--no-textconv",
        ),
    )
    name_status = _parse_name_status(
        _git(
            repository,
            *_diff_arguments(
                target_kind,
                base_sha,
                scope_paths,
                "--name-status",
                "-z",
            ),
        )
    )
    numstat = _parse_numstat(
        _git(
            repository,
            *_diff_arguments(target_kind, base_sha, scope_paths, "--numstat", "-z"),
        )
    )
    untracked = ()
    if target_kind == "working-tree":
        untracked = tuple(sorted(
            (
                *_read_untracked(
                    repository,
                    target_kind,
                    base_sha,
                    scope_paths,
                ),
                *_read_explicit_ignored(
                    repository,
                    target_kind,
                    base_sha,
                    included_ignored_paths,
                ),
            ),
            key=lambda item: item.path,
        ))

    uncommitted = {
        _decode_path(path)
        for path in _git(
            repository,
            *_uncommitted_arguments(target_kind, head_sha, scope_paths),
        ).split(b"\0")
        if path
    }
    uncommitted.update(item.path for item in untracked)
    return _CapturedMaterial(
        patch_digest=patch_digest,
        patch_bytes=patch_bytes,
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
    scope_paths: tuple[str, ...],
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
        material.patch_digest.encode("ascii"),
        str(material.patch_bytes).encode("ascii"),
    ):
        add(value)
    for item in material.untracked:
        add(item.path.encode("utf-8", errors="surrogateescape"))
        add(item.content_digest.encode("ascii"))
        add(str(item.content_bytes).encode("ascii"))
        add(str(item.changed_lines).encode("ascii"))
        add(str(item.material_hint).encode("ascii"))
    for path in scope_paths:
        add(b"scope")
        add(path.encode("utf-8", errors="surrogateescape"))
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


def _matches_path_or_descendant(path: str, roots: Iterable[str]) -> bool:
    normalized = str(PurePosixPath(path))
    return any(
        normalized == root or normalized.startswith(f"{root}/")
        for root in roots
    )


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


def _tracked_content_size(
    repository: Path,
    target_kind: str,
    path: str,
) -> int | None:
    if target_kind == "staged":
        payload = _git(repository, "cat-file", "-s", f":{path}", check=False).strip()
        return int(payload) if payload.isdigit() else None
    absolute = repository / Path(path)
    if absolute.is_symlink():
        return len(os.readlink(absolute).encode("utf-8", errors="surrogateescape"))
    if absolute.is_file():
        return absolute.stat().st_size
    return None


def _is_gitlink(repository: Path, base_sha: str, path: str) -> bool:
    current = _git(repository, "ls-files", "--stage", "-z", "--", path)
    base = _git(repository, "ls-tree", "-z", base_sha, "--", path)
    return any(
        record.startswith(b"160000 ")
        for payload in (current, base)
        for record in payload.split(b"\0")
        if record
    )


def _uses_lfs_filter(
    repository: Path,
    target_kind: str,
    base_sha: str,
    path: str,
) -> bool:
    current_args = ["check-attr"]
    if target_kind == "staged":
        current_args.append("--cached")
    current_args.extend(["-z", "filter", "--", path])
    base_args = [
        "check-attr",
        f"--source={base_sha}",
        "-z",
        "filter",
        "--",
        path,
    ]
    payloads: list[bytes] = []
    for args in (current_args, base_args):
        completed = _run_git(repository, *args)
        if completed.returncode != 0:
            message = completed.stderr.decode("utf-8", errors="replace").strip()
            raise RuntimeError(f"git {' '.join(args)} failed: {message}")
        payloads.append(completed.stdout)
    return any(
        tokens[-1] == b"lfs"
        for payload in payloads
        if (tokens := [token for token in payload.split(b"\0") if token])
    )


def _is_lockfile(path: str) -> bool:
    name = PurePosixPath(path).name.lower()
    return name in LOCKFILE_NAMES or name.endswith((".lock", ".lock.json"))


def capture_git_snapshot(
    *,
    repository: str | Path,
    target_kind: str,
    base: str = "HEAD",
    scope_paths: Iterable[str] = (),
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
    scope = tuple(sorted(_normalize_paths(scope_paths, label="scope path")))
    included_ignored = _normalize_paths(
        included_ignored_paths,
        label="ignored path",
    )
    if normalized_target == "staged" and included_ignored:
        raise ValueError("staged target cannot include ignored worktree paths")
    if scope:
        outside_scope = [
            path
            for path in included_ignored
            if not _matches_path_or_descendant(path, scope)
        ]
        if outside_scope:
            raise ValueError(
                "included ignored path is outside the requested scope: "
                + ", ".join(sorted(outside_scope))
            )

    first = _capture_material(
        root,
        normalized_target,
        base_sha,
        head_sha,
        included_ignored,
        scope,
    )
    second = _capture_material(
        root,
        normalized_target,
        base_sha,
        head_sha,
        included_ignored,
        scope,
    )
    if first != second:
        raise RuntimeError("local target changed while capturing snapshot; retry")

    target_paths = {path for _, path, _ in second.name_status}
    target_paths.update(item.path for item in second.untracked)
    generated = frozenset(
        path
        for path in target_paths
        if _matches_path_or_descendant(path, generated)
    )
    stats = dict(second.numstat)
    uncommitted = frozenset(second.uncommitted_paths)
    entries: list[SnapshotEntry] = []
    metadata_only: list[str] = []
    unavailable_patches = 0
    untracked_by_path = {item.path: item for item in second.untracked}
    tracked_paths = {path for _, path, _ in second.name_status}

    for status, path, source_path in second.name_status:
        replacement = untracked_by_path.get(path)
        content_bytes = (
            replacement.content_bytes
            if replacement is not None
            else _tracked_content_size(root, normalized_target, path)
        )
        changed_lines = stats.get(path)
        if replacement is not None:
            material = "untracked-replacement"
            changed_lines = None
        elif status.startswith("R"):
            material = "rename"
            changed_lines = None
        elif status.startswith("C"):
            material = "copy"
            changed_lines = None
        elif _is_gitlink(root, base_sha, path):
            material = "submodule"
            changed_lines = None
        elif _uses_lfs_filter(root, normalized_target, base_sha, path):
            material = "lfs-pointer"
        elif _is_lockfile(path):
            material = "lockfile"
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
                content_bytes=content_bytes,
                uncommitted=path in uncommitted,
                coverage=coverage,
                omission_reason=omission_reason,
                source_path=source_path,
            )
        )

    for item in second.untracked:
        path = item.path
        if path in tracked_paths:
            continue
        is_generated = path in generated
        if item.material_hint is not None:
            material = item.material_hint
        elif _is_lockfile(path):
            material = "lockfile"
        else:
            material = "generated" if is_generated else (
                "text" if item.is_text else "binary"
            )
        changed_lines = item.changed_lines
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
                content_bytes=item.content_bytes,
                uncommitted=True,
                coverage=coverage,
                omission_reason=omission_reason,
            )
        )

    entries.sort(key=lambda item: item.path)
    changed_lines_total = sum(entry.changed_lines or 0 for entry in entries)
    patch_bytes = second.patch_bytes + sum(
        item.content_bytes or 0 for item in second.untracked
    )
    final = _capture_material(
        root,
        normalized_target,
        base_sha,
        head_sha,
        included_ignored,
        scope,
    )
    if second != final:
        raise RuntimeError("local target changed while capturing snapshot; retry")
    final_head_sha = _git(root, "rev-parse", "--verify", "HEAD^{commit}").decode().strip()
    if final_head_sha != head_sha:
        raise RuntimeError("HEAD changed while capturing snapshot; retry")
    snapshot_id = _fingerprint(
        target_kind=normalized_target,
        base_sha=base_sha,
        head_sha=head_sha,
        material=second,
        generated_paths=generated,
        scope_paths=scope,
    )
    return GitSnapshot(
        schema_version=1,
        target_kind=normalized_target,
        scope_paths=scope,
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
        "--path",
        action="append",
        default=[],
        help="repository-relative file or directory scope; repeat as needed",
    )
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
        scope_paths=args.path,
        generated_paths=args.generated_path,
        included_ignored_paths=args.include_ignored_path,
    )
    print(snapshot_to_json(snapshot))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
