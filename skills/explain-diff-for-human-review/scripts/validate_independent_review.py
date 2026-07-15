#!/usr/bin/env python3
"""Validate structured findings from an optional independent subagent review."""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any


SHA_PATTERN = re.compile(r"^[0-9a-fA-F]{40}$")
DIFF_MODES = frozenset({"small", "standard", "large"})
STATUSES = frozenset({"completed", "unavailable", "failed", "timed_out", "skipped"})
SEVERITIES = frozenset({"critical", "high", "medium", "low", "info"})
CONFIDENCE_LEVELS = frozenset({"high", "medium", "low"})

TOP_LEVEL_FIELDS = frozenset(
    {
        "schema_version",
        "status",
        "base_sha",
        "head_sha",
        "diff_mode",
        "included_paths",
        "omitted_paths",
        "findings",
        "evidence_gaps",
    }
)
FINDING_FIELDS = frozenset(
    {
        "severity",
        "title",
        "path",
        "symbol",
        "line_start",
        "line_end",
        "evidence_ref",
        "failure_scenario",
        "confidence",
        "recommended_validation",
    }
)


def _require_exact_fields(value: dict[str, Any], expected: frozenset[str], name: str) -> None:
    missing = expected - value.keys()
    extra = value.keys() - expected
    if missing or extra:
        details = []
        if missing:
            details.append(f"missing={sorted(missing)}")
        if extra:
            details.append(f"extra={sorted(extra)}")
        raise ValueError(f"{name} fields are invalid: {', '.join(details)}")


def _require_non_empty_string(value: Any, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} must be a non-empty string")
    return value


def _require_string_list(value: Any, name: str) -> list[str]:
    if not isinstance(value, list):
        raise ValueError(f"{name} must be a list")
    items = []
    for index, item in enumerate(value):
        items.append(_require_non_empty_string(item, f"{name}[{index}]"))
    if len(items) != len(set(items)):
        raise ValueError(f"{name} must not contain duplicates")
    return items


def _require_sha(value: Any, name: str) -> str:
    value = _require_non_empty_string(value, name)
    if not SHA_PATTERN.fullmatch(value):
        raise ValueError(f"{name} must be a full 40-character commit SHA")
    return value


def _validate_finding(finding: Any, *, index: int, head_sha: str, included_paths: set[str]) -> None:
    name = f"findings[{index}]"
    if not isinstance(finding, dict):
        raise ValueError(f"{name} must be an object")
    _require_exact_fields(finding, FINDING_FIELDS, name)

    severity = _require_non_empty_string(finding["severity"], f"{name}.severity")
    confidence = _require_non_empty_string(finding["confidence"], f"{name}.confidence")
    if severity not in SEVERITIES:
        raise ValueError(f"{name}.severity is invalid")
    if confidence not in CONFIDENCE_LEVELS:
        raise ValueError(f"{name}.confidence is invalid")

    for field in ("title", "path", "symbol", "evidence_ref", "failure_scenario"):
        _require_non_empty_string(finding[field], f"{name}.{field}")

    if finding["path"] not in included_paths:
        raise ValueError(f"{name}.path must be present in included_paths")

    line_start = finding["line_start"]
    line_end = finding["line_end"]
    if isinstance(line_start, bool) or not isinstance(line_start, int) or line_start < 1:
        raise ValueError(f"{name}.line_start must be a positive integer")
    if isinstance(line_end, bool) or not isinstance(line_end, int) or line_end < line_start:
        raise ValueError(f"{name}.line_end must be an integer at or after line_start")

    expected_evidence_ref = (
        f"{finding['path']}@{head_sha}:L{line_start}-L{line_end}"
    )
    if finding["evidence_ref"] != expected_evidence_ref:
        raise ValueError(
            f"{name}.evidence_ref must exactly match path, head_sha, and line range"
        )

    recommended = _require_string_list(
        finding["recommended_validation"],
        f"{name}.recommended_validation",
    )
    if not recommended:
        raise ValueError(f"{name}.recommended_validation must not be empty")


def validate_independent_review(
    payload: Any,
    *,
    expected_base_sha: str | None = None,
    expected_head_sha: str | None = None,
    expected_mode: str | None = None,
) -> None:
    if not isinstance(payload, dict):
        raise ValueError("payload must be an object")
    _require_exact_fields(payload, TOP_LEVEL_FIELDS, "payload")

    if isinstance(payload["schema_version"], bool) or payload["schema_version"] != 1:
        raise ValueError("schema_version must equal 1")
    status = _require_non_empty_string(payload["status"], "status")
    diff_mode = _require_non_empty_string(payload["diff_mode"], "diff_mode")
    if status not in STATUSES:
        raise ValueError("status is invalid")
    if diff_mode not in DIFF_MODES:
        raise ValueError("diff_mode is invalid")

    base_sha = _require_sha(payload["base_sha"], "base_sha")
    head_sha = _require_sha(payload["head_sha"], "head_sha")
    included_paths = _require_string_list(payload["included_paths"], "included_paths")
    omitted_paths = _require_string_list(payload["omitted_paths"], "omitted_paths")
    evidence_gaps = _require_string_list(payload["evidence_gaps"], "evidence_gaps")

    if set(included_paths) & set(omitted_paths):
        raise ValueError("included_paths and omitted_paths must not overlap")
    if not isinstance(payload["findings"], list):
        raise ValueError("findings must be a list")

    if expected_base_sha:
        expected_base_sha = _require_sha(expected_base_sha, "expected_base_sha")
        if base_sha.lower() != expected_base_sha.lower():
            raise ValueError("base_sha does not match the expected review target")
    if expected_head_sha:
        expected_head_sha = _require_sha(expected_head_sha, "expected_head_sha")
        if head_sha.lower() != expected_head_sha.lower():
            raise ValueError("head_sha does not match the expected review target")
    if expected_mode and diff_mode != expected_mode:
        raise ValueError("diff_mode does not match the expected review target")

    if status != "completed":
        if payload["findings"]:
            raise ValueError("findings must be empty when status is not completed")
        if included_paths:
            raise ValueError("included_paths must be empty when status is not completed")
        if not evidence_gaps:
            raise ValueError("evidence_gaps must disclose the single-agent fallback")
        return

    if not included_paths:
        raise ValueError("included_paths must not be empty for a completed review")
    if omitted_paths and not evidence_gaps:
        raise ValueError("evidence_gaps must disclose omitted_paths")
    for index, finding in enumerate(payload["findings"]):
        _validate_finding(
            finding,
            index=index,
            head_sha=head_sha,
            included_paths=set(included_paths),
        )


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", help="JSON file to validate, or - for stdin")
    parser.add_argument("--expected-base-sha")
    parser.add_argument("--expected-head-sha")
    parser.add_argument("--expected-mode", choices=sorted(DIFF_MODES))
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        if args.input == "-":
            payload = json.load(sys.stdin)
        else:
            payload = json.loads(Path(args.input).read_text(encoding="utf-8"))
        validate_independent_review(
            payload,
            expected_base_sha=args.expected_base_sha,
            expected_head_sha=args.expected_head_sha,
            expected_mode=args.expected_mode,
        )
    except (OSError, json.JSONDecodeError, ValueError) as exc:
        print(f"invalid independent review: {exc}", file=sys.stderr)
        return 2

    print(json.dumps({"valid": True}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
