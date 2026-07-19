#!/usr/bin/env python3
"""Classify diff size and select a bounded detail-delivery policy."""

from __future__ import annotations

import argparse
import json
from dataclasses import asdict, dataclass


SMALL_MAX_FILES = 20
SMALL_MAX_CHANGED_LINES = 800
SMALL_MAX_PATCH_BYTES = 128 * 1024

STANDARD_MAX_FILES = 80
STANDARD_MAX_CHANGED_LINES = 4_000
STANDARD_MAX_PATCH_BYTES = 1024 * 1024

GITHUB_HOST_ALIASES = frozenset({"github", "github.com"})
TARGET_KINDS = frozenset({"committed", "staged", "working-tree"})


@dataclass(frozen=True)
class DiffSizeDecision:
    mode: str
    detail_delivery: str
    evidence_mode: str
    fixed_compare_covers_target: bool
    permalink_gap_files: int
    changed_files: int
    changed_lines: int
    patch_bytes: int
    unavailable_patches: int
    evidence_complete: bool
    reasons: tuple[str, ...]


def classify_diff_size(
    *,
    changed_files: int,
    changed_lines: int,
    patch_bytes: int,
    unavailable_patches: int = 0,
    host: str = "unknown",
    target_kind: str = "committed",
    permalink_gap_files: int | None = None,
) -> DiffSizeDecision:
    metrics = {
        "changed_files": changed_files,
        "changed_lines": changed_lines,
        "patch_bytes": patch_bytes,
        "unavailable_patches": unavailable_patches,
    }
    for name, value in metrics.items():
        if value < 0:
            raise ValueError(f"{name} must be non-negative")

    normalized_target = target_kind.strip().lower()
    if normalized_target not in TARGET_KINDS:
        raise ValueError(
            "target_kind must be one of: " + ", ".join(sorted(TARGET_KINDS))
        )
    if permalink_gap_files is None:
        permalink_gap_files = 0 if normalized_target == "committed" else changed_files
    if permalink_gap_files < 0:
        raise ValueError("permalink_gap_files must be non-negative")
    if normalized_target == "committed" and permalink_gap_files:
        raise ValueError("committed target cannot have permalink_gap_files")

    if (
        changed_files <= SMALL_MAX_FILES
        and changed_lines <= SMALL_MAX_CHANGED_LINES
        and patch_bytes <= SMALL_MAX_PATCH_BYTES
    ):
        mode = "small"
    elif (
        changed_files <= STANDARD_MAX_FILES
        and changed_lines <= STANDARD_MAX_CHANGED_LINES
        and patch_bytes <= STANDARD_MAX_PATCH_BYTES
    ):
        mode = "standard"
    else:
        mode = "large"

    normalized_host = host.strip().lower().rstrip(".")
    immutable_target = normalized_target == "committed"
    evidence_mode = (
        "immutable-git" if immutable_target else "mutable-local-snapshot"
    )
    github_target = normalized_host in GITHUB_HOST_ALIASES
    fixed_compare_covers_target = github_target and permalink_gap_files == 0
    if github_target and permalink_gap_files:
        detail_delivery = "local-snapshot-metadata-only"
    elif github_target:
        detail_delivery = "pinned-github-links-only"
    elif mode == "small":
        detail_delivery = "inline"
    elif mode == "standard":
        detail_delivery = "collapsed-bounded-details"
    else:
        detail_delivery = "bounded-appendices-or-explicit-omission"

    reasons = [
        f"files={changed_files}",
        f"changed_lines={changed_lines}",
        f"patch_bytes={patch_bytes}",
    ]
    if unavailable_patches:
        reasons.append(f"unavailable_patches={unavailable_patches}")
    reasons.append(f"target_kind={normalized_target}")
    if permalink_gap_files:
        reasons.append(f"permalink_gap_files={permalink_gap_files}")
    if github_target and permalink_gap_files:
        reasons.append("immutable_github_links_do_not_cover_mutable_content")

    evidence_complete = unavailable_patches == 0
    if github_target and permalink_gap_files:
        evidence_complete = False

    return DiffSizeDecision(
        mode=mode,
        detail_delivery=detail_delivery,
        evidence_mode=evidence_mode,
        fixed_compare_covers_target=fixed_compare_covers_target,
        permalink_gap_files=permalink_gap_files,
        changed_files=changed_files,
        changed_lines=changed_lines,
        patch_bytes=patch_bytes,
        unavailable_patches=unavailable_patches,
        evidence_complete=evidence_complete,
        reasons=tuple(reasons),
    )


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--changed-files", type=int, required=True)
    parser.add_argument("--changed-lines", type=int, required=True)
    parser.add_argument("--patch-bytes", type=int, required=True)
    parser.add_argument("--unavailable-patches", type=int, default=0)
    parser.add_argument(
        "--host",
        default="unknown",
        help="hosting platform alias or parsed hostname, for example github or github.com",
    )
    parser.add_argument(
        "--permalink-gap-files",
        type=int,
        help=(
            "changed paths absent from the immutable head; mutable targets default "
            "conservatively to all changed files and cancellation paths may make "
            "this count exceed base-relative changed_files"
        ),
    )
    parser.add_argument(
        "--target-kind",
        choices=sorted(TARGET_KINDS),
        default="committed",
        help="committed, staged, or working-tree evidence target",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    decision = classify_diff_size(
        changed_files=args.changed_files,
        changed_lines=args.changed_lines,
        patch_bytes=args.patch_bytes,
        unavailable_patches=args.unavailable_patches,
        host=args.host,
        target_kind=args.target_kind,
        permalink_gap_files=args.permalink_gap_files,
    )
    print(json.dumps(asdict(decision), ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
