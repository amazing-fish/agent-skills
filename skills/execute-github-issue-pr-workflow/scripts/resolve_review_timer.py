#!/usr/bin/env python3
"""Resolve a UTC-safe one-shot review timer and verify its next run."""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError


REVIEW_DELAY = timedelta(minutes=6)
NEXT_RUN_TOLERANCE = timedelta(seconds=60)
WEEKDAY_CODES = ("MO", "TU", "WE", "TH", "FR", "SA", "SU")


@dataclass(frozen=True)
class NextRunDecision:
    decision: str
    reason: str
    verified_at_utc: datetime
    resolved_next_run_utc: datetime | None
    delta_seconds: float | None


@dataclass(frozen=True)
class ReviewTimerResolution:
    user_timezone: str
    now_utc: datetime
    target_at_utc: datetime
    target_at_local: datetime
    rrule_fields: dict[str, int | str]
    next_run: NextRunDecision


def _require_aware(value: datetime, name: str) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{name} must include a timezone")
    return value


def compute_target_at_utc(*, now: datetime, user_timezone: str) -> datetime:
    zone = ZoneInfo(user_timezone)
    now_in_user_timezone = _require_aware(now, "now").astimezone(zone)
    return now_in_user_timezone.astimezone(timezone.utc) + REVIEW_DELAY


def derive_utc_rrule_fields(target_at_utc: datetime) -> dict[str, int | str]:
    target = _require_aware(
        target_at_utc,
        "target_at_utc",
    ).astimezone(timezone.utc)
    return {
        "BYHOUR": target.hour,
        "BYMINUTE": target.minute,
        "BYSECOND": target.second,
        "BYDAY": WEEKDAY_CODES[target.weekday()],
    }


def verify_resolved_next_run(
    *,
    target_at_utc: datetime,
    resolved_next_run: datetime | None,
    verification_time: datetime | None = None,
) -> NextRunDecision:
    verified_at_utc = (
        datetime.now(timezone.utc)
        if verification_time is None
        else _require_aware(
            verification_time,
            "verification_time",
        ).astimezone(timezone.utc)
    )
    target = _require_aware(
        target_at_utc,
        "target_at_utc",
    ).astimezone(timezone.utc)

    if resolved_next_run is None:
        return NextRunDecision(
            decision="cleanup",
            reason="unavailable",
            verified_at_utc=verified_at_utc,
            resolved_next_run_utc=None,
            delta_seconds=None,
        )

    resolved = _require_aware(
        resolved_next_run,
        "resolved_next_run",
    ).astimezone(timezone.utc)
    delta_seconds = abs((resolved - target).total_seconds())
    if resolved <= verified_at_utc:
        return NextRunDecision(
            decision="cleanup",
            reason="not_in_future",
            verified_at_utc=verified_at_utc,
            resolved_next_run_utc=resolved,
            delta_seconds=delta_seconds,
        )
    if delta_seconds > NEXT_RUN_TOLERANCE.total_seconds():
        return NextRunDecision(
            decision="cleanup",
            reason="out_of_tolerance",
            verified_at_utc=verified_at_utc,
            resolved_next_run_utc=resolved,
            delta_seconds=delta_seconds,
        )
    return NextRunDecision(
        decision="accept",
        reason="within_tolerance",
        verified_at_utc=verified_at_utc,
        resolved_next_run_utc=resolved,
        delta_seconds=delta_seconds,
    )


def resolve_review_timer(
    *,
    now: datetime,
    user_timezone: str,
    resolved_next_run: datetime | None = None,
    verification_time: datetime | None = None,
) -> ReviewTimerResolution:
    zone = ZoneInfo(user_timezone)
    now_utc = _require_aware(now, "now").astimezone(zone).astimezone(timezone.utc)
    target_at_utc = compute_target_at_utc(
        now=now,
        user_timezone=user_timezone,
    )
    return ReviewTimerResolution(
        user_timezone=user_timezone,
        now_utc=now_utc,
        target_at_utc=target_at_utc,
        target_at_local=target_at_utc.astimezone(zone),
        rrule_fields=derive_utc_rrule_fields(target_at_utc),
        next_run=verify_resolved_next_run(
            target_at_utc=target_at_utc,
            resolved_next_run=resolved_next_run,
            verification_time=verification_time,
        ),
    )


def _parse_datetime(value: str, name: str) -> datetime:
    normalized = value[:-1] + "+00:00" if value.endswith(("Z", "z")) else value
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError as exc:
        raise ValueError(f"{name} must be an ISO 8601 datetime") from exc
    return _require_aware(parsed, name)


def _to_payload(resolution: ReviewTimerResolution) -> dict[str, object]:
    return {
        "user_timezone": resolution.user_timezone,
        "now_utc": resolution.now_utc.isoformat(),
        "target_at_utc": resolution.target_at_utc.isoformat(),
        "target_at_local": resolution.target_at_local.isoformat(),
        "rrule_fields": resolution.rrule_fields,
        "next_run": {
            "decision": resolution.next_run.decision,
            "reason": resolution.next_run.reason,
            "verified_at_utc": resolution.next_run.verified_at_utc.isoformat(),
            "resolved_next_run_utc": (
                resolution.next_run.resolved_next_run_utc.isoformat()
                if resolution.next_run.resolved_next_run_utc is not None
                else None
            ),
            "delta_seconds": resolution.next_run.delta_seconds,
        },
    }


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--timezone", required=True, dest="user_timezone")
    parser.add_argument(
        "--now",
        help="Timezone-aware ISO 8601 current time; defaults to the current user-zone time",
    )
    parser.add_argument(
        "--resolved-next-run",
        help="Timezone-aware ISO 8601 resolved next run; omit when unavailable",
    )
    parser.add_argument(
        "--verification-time",
        help="Timezone-aware ISO 8601 verification time; defaults to the current UTC time",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        zone = ZoneInfo(args.user_timezone)
        now = (
            _parse_datetime(args.now, "now")
            if args.now
            else datetime.now(zone)
        )
        resolved_next_run = (
            _parse_datetime(args.resolved_next_run, "resolved_next_run")
            if args.resolved_next_run
            else None
        )
        verification_time = (
            _parse_datetime(args.verification_time, "verification_time")
            if args.verification_time
            else None
        )
        resolution = resolve_review_timer(
            now=now,
            user_timezone=args.user_timezone,
            resolved_next_run=resolved_next_run,
            verification_time=verification_time,
        )
    except (TypeError, ValueError, ZoneInfoNotFoundError) as exc:
        print(f"invalid review timer input: {exc}", file=sys.stderr)
        return 2

    print(json.dumps(_to_payload(resolution), ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
