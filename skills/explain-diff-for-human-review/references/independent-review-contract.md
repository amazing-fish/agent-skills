# Independent subagent review contract

Read this reference only when the optional independent review stage is selected.

## Input boundary

Give the subagent only task-local evidence:

- repository identity plus immutable `base_sha` and `head_sha`;
- selected diff mode and the exact included and omitted paths;
- bounded patch or diff metadata, relevant tests, contracts, and constraints;
- a read-only instruction: do not edit files, post reviews, approve changes, or make merge decisions.

Do not provide the main agent's expected conclusion, suspected finding, intended fix, or draft report. Never use a moving branch name as the only source reference.

For `small`, include the full relevant changed-file set when evidence is available. For `standard`, prioritize high-risk and representative files and list every omitted path. For `large`, use only a bounded high-risk slice when the extra review is clearly useful; disclose that it is not complete coverage.

## Output contract

Return one JSON object and no prose:

```json
{
  "schema_version": 1,
  "status": "completed",
  "base_sha": "40-character commit SHA",
  "head_sha": "40-character commit SHA",
  "diff_mode": "small",
  "included_paths": ["src/example.py"],
  "omitted_paths": [],
  "findings": [
    {
      "severity": "medium",
      "title": "Concise finding",
      "path": "src/example.py",
      "symbol": "run",
      "line_start": 10,
      "line_end": 12,
      "evidence_ref": "src/example.py@<head_sha>:L10-L12",
      "failure_scenario": "Concrete behavior that can fail.",
      "confidence": "high",
      "recommended_validation": ["Run a focused regression test."]
    }
  ],
  "evidence_gaps": []
}
```

Allowed statuses are `completed`, `unavailable`, `failed`, `timed_out`, and `skipped`. A non-completed status must return empty `included_paths` and `findings`, plus at least one `evidence_gaps` entry explaining that the main agent used the single-agent fallback.

`severity` is one of `critical`, `high`, `medium`, `low`, or `info`; `confidence` is `high`, `medium`, or `low`. Every finding must use the exact canonical evidence reference `<path>@<head_sha>:L<line_start>-L<line_end>` so the path, fixed version, and line range cannot drift independently.

Validate the payload with `scripts/validate_independent_review.py`, passing the expected base SHA, head SHA, and diff mode. Discard invalid or non-completed findings.
