import importlib.util
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
import subprocess
import sys
import unittest
from zoneinfo import ZoneInfo


ROOT = Path(__file__).resolve().parents[1]
SCRIPT_PATH = (
    ROOT
    / "skills"
    / "execute-github-issue-pr-workflow"
    / "scripts"
    / "resolve_review_timer.py"
)
CONTRACT_PATH = (
    ROOT
    / "skills"
    / "execute-github-issue-pr-workflow"
    / "references"
    / "review-timer-contract.json"
)
SCHEDULED_SURFACES = {
    "relative_one_shot",
    "heartbeat_rrule_only",
    "dtstart_or_count_rejected",
}
UNSCHEDULED_SURFACES = {
    "heartbeat_rrule_rejected",
    "created_timer",
}
EXPECTED_SCHEDULE_BY_CASE = {
    "native_relative_one_shot": (
        "relative_one_shot",
        "now_utc_plus_6m",
    ),
    "rrule_only_heartbeat": (
        "heartbeat_rrule_only",
        "target_at_utc",
    ),
    "relative_schedule_rejected": (
        "dtstart_or_count_rejected",
        "target_at_utc",
    ),
    "utc_heartbeat_rejected": (
        "heartbeat_rrule_rejected",
        "none",
    ),
    "next_run_out_of_tolerance": (
        "created_timer",
        "none",
    ),
    "next_run_unverifiable": (
        "created_timer",
        "none",
    ),
}


def _load_resolver():
    spec = importlib.util.spec_from_file_location(
        "execute_github_issue_pr_workflow_review_timer",
        SCRIPT_PATH,
    )
    if spec is None or spec.loader is None:
        raise RuntimeError("Could not load resolve_review_timer.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


resolver = _load_resolver()


def _scheduled_at_from_contract_basis(schedule_basis, resolution):
    if schedule_basis == "now_utc_plus_6m":
        return resolution.now_utc + resolver.REVIEW_DELAY
    if schedule_basis == "target_at_utc":
        return resolution.target_at_utc
    if schedule_basis == "local_wall_time":
        return resolution.target_at_local.replace(tzinfo=timezone.utc)
    if schedule_basis == "none":
        return None
    raise ValueError(f"Unknown schedule_basis: {schedule_basis}")


class ReviewTimerResolverTests(unittest.TestCase):
    def setUp(self):
        self.started_at = datetime(
            2026,
            7,
            27,
            1,
            32,
            30,
            tzinfo=ZoneInfo("Asia/Shanghai"),
        )
        self.now_utc = self.started_at.astimezone(timezone.utc)
        self.target_at_utc = self.now_utc + timedelta(minutes=6)

    def test_resolves_target_and_rrule_fields_from_real_zoneinfo(self):
        resolution = resolver.resolve_review_timer(
            now=self.started_at,
            user_timezone="Asia/Shanghai",
            resolved_next_run=self.target_at_utc,
            verification_time=self.now_utc,
        )

        self.assertEqual(
            datetime.fromisoformat("2026-07-26T17:38:30+00:00"),
            resolution.target_at_utc,
        )
        self.assertEqual(
            {
                "BYHOUR": 17,
                "BYMINUTE": 38,
                "BYSECOND": 30,
                "BYDAY": "SU",
            },
            resolution.rrule_fields,
        )
        self.assertEqual("Asia/Shanghai", resolution.target_at_local.tzinfo.key)
        self.assertEqual("accept", resolution.next_run.decision)

    def test_accepts_only_future_runs_within_inclusive_tolerance(self):
        for offset_seconds in (-60, 0, 60):
            with self.subTest(offset_seconds=offset_seconds):
                decision = resolver.verify_resolved_next_run(
                    target_at_utc=self.target_at_utc,
                    resolved_next_run=(
                        self.target_at_utc
                        + timedelta(seconds=offset_seconds)
                    ),
                    verification_time=self.now_utc,
                )
                self.assertEqual("accept", decision.decision)

        for resolved_next_run, reason in (
            (self.now_utc, "not_in_future"),
            (
                self.target_at_utc + timedelta(seconds=60, microseconds=1),
                "out_of_tolerance",
            ),
            (None, "unavailable"),
        ):
            with self.subTest(reason=reason):
                decision = resolver.verify_resolved_next_run(
                    target_at_utc=self.target_at_utc,
                    resolved_next_run=resolved_next_run,
                    verification_time=self.now_utc,
                )
                self.assertEqual("cleanup", decision.decision)
                self.assertEqual(reason, decision.reason)

    def test_compares_future_run_to_verification_time(self):
        decision = resolver.verify_resolved_next_run(
            target_at_utc=self.target_at_utc,
            resolved_next_run=self.target_at_utc,
            verification_time=self.target_at_utc + timedelta(seconds=1),
        )

        self.assertEqual("cleanup", decision.decision)
        self.assertEqual("not_in_future", decision.reason)

    def test_contract_cases_drive_next_run_decisions(self):
        cases = json.loads(CONTRACT_PATH.read_text(encoding="utf-8"))
        resolved_by_evidence = {
            "resolved_next_run": self.target_at_utc,
            "resolved_or_persisted_first_occurrence": self.target_at_utc,
            "out_of_tolerance": self.target_at_utc + timedelta(seconds=61),
            "unavailable": None,
        }
        expected_by_outcome = {
            "create_and_verify": "accept",
            "cleanup_pending": "cleanup",
        }

        tested_case_ids = []
        for case in cases:
            if case["evidence"] not in resolved_by_evidence:
                continue
            self.assertIn(case["outcome"], expected_by_outcome)
            decision = resolver.verify_resolved_next_run(
                target_at_utc=self.target_at_utc,
                resolved_next_run=resolved_by_evidence[case["evidence"]],
                verification_time=self.now_utc,
            )
            self.assertEqual(
                expected_by_outcome[case["outcome"]],
                decision.decision,
                case["id"],
            )
            tested_case_ids.append(case["id"])

        self.assertEqual(4, len(tested_case_ids))

    def test_contract_schedule_basis_and_surface_match_resolver_behavior(self):
        cases = json.loads(CONTRACT_PATH.read_text(encoding="utf-8"))
        resolution = resolver.resolve_review_timer(
            now=self.started_at,
            user_timezone="Asia/Shanghai",
            resolved_next_run=self.target_at_utc,
            verification_time=self.now_utc,
        )
        controlled_surfaces = SCHEDULED_SURFACES | UNSCHEDULED_SURFACES
        self.assertEqual(
            controlled_surfaces,
            {case["surface"] for case in cases},
        )
        self.assertEqual(
            set(EXPECTED_SCHEDULE_BY_CASE),
            {case["id"] for case in cases},
        )

        for case in cases:
            with self.subTest(case_id=case["id"]):
                self.assertEqual(
                    EXPECTED_SCHEDULE_BY_CASE[case["id"]],
                    (case["surface"], case["schedule_basis"]),
                )
                self.assertIn(case["surface"], controlled_surfaces)
                scheduled_at = _scheduled_at_from_contract_basis(
                    case["schedule_basis"],
                    resolution,
                )
                if case["surface"] in SCHEDULED_SURFACES:
                    self.assertEqual(
                        resolution.target_at_utc,
                        scheduled_at,
                        case["id"],
                    )
                    if case["surface"] != "relative_one_shot":
                        self.assertEqual(
                            resolution.rrule_fields,
                            resolver.derive_utc_rrule_fields(scheduled_at),
                            case["id"],
                        )
                else:
                    self.assertIsNone(scheduled_at, case["id"])

    def test_london_winter_and_summer_resolve_the_same_local_delay(self):
        cases = (
            (
                "winter",
                datetime(
                    2026,
                    1,
                    15,
                    12,
                    0,
                    tzinfo=ZoneInfo("Europe/London"),
                ),
                datetime.fromisoformat("2026-01-15T12:06:00+00:00"),
                12,
            ),
            (
                "summer",
                datetime(
                    2026,
                    7,
                    15,
                    12,
                    0,
                    tzinfo=ZoneInfo("Europe/London"),
                ),
                datetime.fromisoformat("2026-07-15T11:06:00+00:00"),
                11,
            ),
        )

        observed_offsets = []
        for season, started_at, expected_target_at_utc, expected_byhour in cases:
            with self.subTest(season=season):
                now_utc = started_at.astimezone(timezone.utc)
                resolution = resolver.resolve_review_timer(
                    now=started_at,
                    user_timezone="Europe/London",
                    resolved_next_run=expected_target_at_utc
                    + resolver.NEXT_RUN_TOLERANCE,
                    verification_time=now_utc,
                )
                self.assertEqual(
                    expected_target_at_utc,
                    resolution.target_at_utc,
                )
                self.assertEqual(
                    started_at + resolver.REVIEW_DELAY,
                    resolution.target_at_local,
                )
                self.assertEqual(
                    expected_byhour,
                    resolution.rrule_fields["BYHOUR"],
                )
                self.assertEqual(60, resolution.next_run.delta_seconds)
                self.assertEqual("accept", resolution.next_run.decision)
                observed_offsets.append(resolution.target_at_local.utcoffset())

        self.assertEqual(
            [timedelta(0), timedelta(hours=1)],
            observed_offsets,
        )

    def test_crosses_london_fall_back_on_the_absolute_timeline(self):
        started_at = datetime(
            2026,
            10,
            25,
            0,
            58,
            tzinfo=timezone.utc,
        ).astimezone(ZoneInfo("Europe/London"))
        expected_target_at_utc = datetime(
            2026,
            10,
            25,
            1,
            4,
            tzinfo=timezone.utc,
        )

        resolution = resolver.resolve_review_timer(
            now=started_at,
            user_timezone="Europe/London",
            resolved_next_run=expected_target_at_utc,
            verification_time=started_at.astimezone(timezone.utc),
        )

        self.assertEqual(timedelta(hours=1), started_at.utcoffset())
        self.assertEqual(expected_target_at_utc, resolution.target_at_utc)
        self.assertEqual(
            timedelta(minutes=6),
            resolution.target_at_utc - started_at.astimezone(timezone.utc),
        )
        self.assertEqual(timedelta(0), resolution.target_at_local.utcoffset())
        self.assertEqual(1, resolution.target_at_local.fold)
        self.assertEqual(
            {
                "BYHOUR": 1,
                "BYMINUTE": 4,
                "BYSECOND": 0,
                "BYDAY": "SU",
            },
            resolution.rrule_fields,
        )
        self.assertEqual("accept", resolution.next_run.decision)

    def test_cli_emits_machine_readable_zoneinfo_resolution(self):
        completed = subprocess.run(
            [
                sys.executable,
                str(SCRIPT_PATH),
                "--timezone",
                "Asia/Shanghai",
                "--now",
                self.started_at.isoformat(),
                "--resolved-next-run",
                self.target_at_utc.isoformat(),
                "--verification-time",
                self.now_utc.isoformat(),
            ],
            cwd=ROOT,
            capture_output=True,
            text=True,
            check=False,
        )

        self.assertEqual(0, completed.returncode, completed.stderr)
        payload = json.loads(completed.stdout)
        self.assertEqual(
            "2026-07-26T17:38:30+00:00",
            payload["target_at_utc"],
        )
        self.assertEqual("SU", payload["rrule_fields"]["BYDAY"])
        self.assertEqual("accept", payload["next_run"]["decision"])
        self.assertEqual(
            self.now_utc.isoformat(),
            payload["next_run"]["verified_at_utc"],
        )

    def test_rejects_naive_datetimes(self):
        with self.assertRaisesRegex(ValueError, "now must include a timezone"):
            resolver.compute_target_at_utc(
                now=datetime(2026, 7, 27, 1, 32, 30),
                user_timezone="Asia/Shanghai",
            )


if __name__ == "__main__":
    unittest.main()
