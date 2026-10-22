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


@dataclass(frozen=True)
class DiffSizeDecision:
    mode: str
    detail_delivery: str
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
    if normalized_host in GITHUB_HOST_ALIASES:
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

    return DiffSizeDecision(
        mode=mode,
        detail_delivery=detail_delivery,
        changed_files=changed_files,
        changed_lines=changed_lines,
        patch_bytes=patch_bytes,
        unavailable_patches=unavailable_patches,
        evidence_complete=unavailable_patches == 0,
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
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    decision = classify_diff_size(
        changed_files=args.changed_files,
        changed_lines=args.changed_lines,
        patch_bytes=args.patch_bytes,
        unavailable_patches=args.unavailable_patches,
        host=args.host,
    )
    print(json.dumps(asdict(decision), ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
