#!/usr/bin/env python3
"""Resolve a writable report path without mutating the installed skill."""

from __future__ import annotations

import argparse
import json
import re
import tempfile
from dataclasses import asdict, dataclass
from pathlib import Path


@dataclass(frozen=True)
class ResolvedReportPath:
    path: str
    source: str


def report_filename(target: str) -> str:
    normalized = re.sub(r"[^A-Za-z0-9._-]+", "-", target).strip(".-")
    if not normalized:
        normalized = "target"
    return f"explain-diff-{normalized[:120]}.html"


def resolve_report_path(
    *,
    target: str,
    output_path: str | None = None,
    repository_root: str | None = None,
    workspace_root: str | None = None,
    temporary_root: str | None = None,
) -> ResolvedReportPath:
    filename = report_filename(target)

    if output_path:
        explicit = Path(output_path).expanduser()
        path = explicit if explicit.suffix.lower() == ".html" else explicit / filename
        source = "explicit"
    elif repository_root:
        path = Path(repository_root).expanduser() / "reports" / filename
        source = "repository"
    elif workspace_root:
        path = Path(workspace_root).expanduser() / "reports" / filename
        source = "workspace"
    else:
        root = Path(temporary_root).expanduser() if temporary_root else Path(tempfile.gettempdir())
        path = root / "reports" / filename
        source = "temporary"

    absolute = path.resolve()
    absolute.parent.mkdir(parents=True, exist_ok=True)
    return ResolvedReportPath(path=str(absolute), source=source)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--target", required=True)
    parser.add_argument("--output-path")
    parser.add_argument("--repository-root")
    parser.add_argument("--workspace-root")
    parser.add_argument("--temporary-root")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    resolved = resolve_report_path(
        target=args.target,
        output_path=args.output_path,
        repository_root=args.repository_root,
        workspace_root=args.workspace_root,
        temporary_root=args.temporary_root,
    )
    print(json.dumps(asdict(resolved), ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
