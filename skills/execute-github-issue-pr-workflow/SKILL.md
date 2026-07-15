---
name: execute-github-issue-pr-workflow
description: Execute a governed GitHub delivery loop from problem analysis through Issue creation, focused implementation, pull request, state-driven Codex review completion, comment resolution, human-authorized merge, Issue reconciliation, and documentation updates. Use when the user asks to autonomously or repeatedly advance repository work, work through one or more Issues, submit and shepherd PRs, handle review comments, continue a GitHub roadmap, or follow their established Issue-to-PR workflow.
---

# Execute GitHub Issue–PR Workflow

Treat GitHub remote state as authoritative. Treat local clones as working copies. Never commit directly to the default branch.

## Establish scope and authority

1. Read repository instructions and inspect the working tree, current branch, remote, default branch, open Issues, open PRs, checks, and relevant roadmap/docs.
2. Preserve unrelated user changes. Do not let multiple agents make broad edits on the same branch.
3. Determine repository ownership from verified GitHub metadata:
   - For a repository owned by the user, create a ready-for-review PR by default; no extra authorization is needed to create it.
   - For an external upstream repository, prepare and push changes only to the user's fork without contacting upstream maintainers. Obtain explicit authorization before opening any PR against upstream; after authorization, create that upstream PR as Draft by default.
4. Keep one active implementation Issue at a time. In default mode, keep only its corresponding PR active; automatic staging mode may accumulate multiple reviewed, unmerged PRs while still implementing Issues sequentially.
5. Ask only when a missing decision materially changes architecture, public APIs, schemas, migration, credentials, safety, destructive actions, cost, or user-visible behavior.

## Select the progression mode

Use **default approval mode** unless the user explicitly enables **automatic staging mode**.

- **Default approval mode:** after review gates pass, generate the human-readable diff report and ask for one explicit decision that authorizes both merging the exact current HEAD and proceeding to the next Issue. Do not merge or start the next Issue without that approval.
- **Automatic staging mode:** after review gates pass, generate the human-readable diff report. If it reports no merge risk and no blocking decision, leave the PR open and ready as `staged`, keep its Issue open, record its HEAD and dependencies, and continue to the next Issue without per-PR approval or merge. This mode never means auto-merge.

In automatic staging mode, branch independent Issues from the current default branch so each PR remains independently reviewable. Use an explicit stacked-PR chain only when the next Issue genuinely depends on unmerged behavior; record the base/head relationship and required merge order.

Stop automatic staging and require human direction when the vision is complete, the actionable Issue queue is empty, the diff report identifies merge risk or a decision, accumulated PRs conflict, or the next work would materially change scope. Present the staged PRs, exact HEADs, dependency/merge order, risks, and options to merge, revise, drop, rebase, or redefine the vision.

## Create or select the Issue

1. Confirm whether an existing Issue already covers the problem. Avoid duplicates.
2. Create an Issue before non-trivial implementation. Include context, observed/desired behavior, bounded scope, acceptance criteria, risks, and validation plan.
3. Do not close an Issue merely because code was committed or a PR was opened.
4. Use neutral references such as `Refs #N`, `Related to #N`, or `Addresses #N` unless the user explicitly authorizes automatic closure.
5. Defer explicitly shelved topics and do not count them toward delivery milestones.

## Implement narrowly

1. Branch from the correct, current base using an established repository naming convention such as `fix/issue-N-*` or `feature/issue-N-*`.
2. Implement only the Issue acceptance criteria. Avoid opportunistic refactors and unrelated file churn.
3. Add focused regression tests and update affected docs when behavior or contracts change.
4. Run relevant unit tests plus configured lint/type checks. Record exact commands and outcomes. If a check cannot run, state why and provide best-effort verification.
5. Commit and push focused changes. Never treat unpushed local state as completed work.

## Open or update the PR

Include:

- linked Issue(s) using the authorized reference form;
- what changed and why;
- what was deliberately not changed;
- risks and rollback considerations;
- exact validation commands and results;
- screenshots or observable output when user-visible behavior changed.

Keep the PR ready for review for user-owned repositories unless implementation is incomplete or the user requests Draft. Always return the full clickable PR URL.

Never merge a PR in the same assistant turn in which it was created. Waiting, polling, scheduled execution, or auto-merge does not bypass this boundary.

## Run the review loop

For every new final PR HEAD:

1. Record the exact HEAD SHA, the time this HEAD was first observed for the current cycle (`head_observed_at`), existing reviews, and whether a fallback `@codex review` has already been posted for this HEAD.
2. Wait 6 minutes from this cycle's `head_observed_at` (the initial ready-for-review PR submission or a later pushed HEAD), then refresh GitHub PR reviews, review comments, conversation comments, checks, and robot status.
3. Classify the refreshed state:
   - **Review not triggered:** if neither an in-progress signal nor a Codex review bound to this HEAD exists, post `@codex review current HEAD <short-sha>` exactly once for this HEAD, record the comment URL/time, wait 6 minutes, and refresh again.
   - **Review in progress:** do not post another mention. Wait another 6 minutes and refresh again.
   - **Review completed and bound:** continue only when the review's `commit_id` exactly matches the recorded HEAD or the review body/status explicitly names that HEAD SHA as the reviewed commit. Re-confirm that HEAD has not changed.
   - **Review completed but unbound:** never accept submission time alone. If no fallback was posted for this HEAD, post `@codex review current HEAD <short-sha>` once and wait 6 minutes. Require the resulting review to explicitly bind to the recorded HEAD; otherwise report the review as unverifiable and stop.
4. A completed, HEAD-bound Codex review with no findings is a valid result. Absence of comments, elapsed time, acknowledgement, or submission time alone is not completion.
5. If the execution environment reaches its waiting limit, report `Codex review pending` with PR URL, HEAD, `head_observed_at`, fallback request URL/time if used, observed robot state, and last refresh time. Stop or resume later; never infer approval from timeout.
6. After the matching review arrives, re-read the latest HEAD and check:
   - Issue comments, PR conversation, inline comments, reviews, requested changes, and unresolved threads;
   - checks/workflows, mergeability, conflicts, base-behind status, and stacked-branch relationships;
   - acceptance criteria, docs, tests, and whether each comment still applies to the current code.
7. If actionable feedback or a failed check exists, handle it. Any pushed fix creates a new HEAD and restarts this 6-minute cycle; allow at most one fallback `@codex review` mention for that new HEAD.
8. If the completed Codex review has no actionable findings and all other gates pass, report readiness; do not infer merge authorization outside automatic staging mode.

## Handle review findings

Classify each finding:

- **Small and in scope:** fix the root cause on the original PR branch, search for sibling instances, add a focused regression test, run narrow then broader validation, and reply with concrete evidence.
- **In scope but risky:** keep the PR open; add a sub-Issue/checklist or split the work if the original goal, public contract, rollback boundary, or diff size changes materially.
- **Out of scope or architectural:** do not bloat the PR. Create a follow-up Issue and keep the current PR focused.

Resolve a thread only after the fix is present and verified, or after an explicit rationale is accepted. Summarize each addressed item and request re-review. Put review fixes in the lowest branch that owns the behavior, then update dependent stacked branches.

## Gate the merge

Treat a PR as merge-ready only when:

- the linked Issue acceptance criteria are satisfied;
- required checks pass on the latest HEAD;
- no blocking or unresolved review feedback remains;
- risks and validation evidence are recorded;
- docs match the current implementation;
- the latest HEAD has a matching completed Codex GitHub review, not merely an acknowledgement or timeout;
- no scope ambiguity remains.

At workflow start, check whether the user's `explain-diff-for-human-review` skill is installed. Its absence does not block Issue implementation or PR review, but disclose the missing merge dependency before doing long-running work.

Before merging or staging, require the installed `explain-diff-for-human-review` skill and present its review artifact. Do not silently substitute an ad hoc summary for the missing skill. Never reuse a report or approval after HEAD changes.

In default approval mode, obtain explicit user approval for the exact PR and current HEAD; that decision also authorizes proceeding to the next Issue after a successful merge. In automatic staging mode, do not request per-PR approval when the report has no merge risk: leave the PR unmerged, record it as staged, and continue. A report with merge risk or an unresolved decision always stops automatic progression for human direction.

After approval, recheck HEAD, checks, unresolved threads, and mergeability immediately before merging. Use the repository's permitted merge strategy. Never force-push, bypass protection, or silently enable auto-merge.

Never merge a staged PR merely because automatic staging mode is enabled. Merge only after the final human decision names the exact staged PRs or approved merge order.

## Reconcile after merge

1. Verify the remote default branch contains the merged commit and that deployment/check state is healthy when applicable.
2. Reconcile Issue status against actual landed code and acceptance criteria; distinguish automatic closure, manual closure, partial completion, and code-complete-but-open states.
3. Close or update the Issue only within the user's authorization. Record residual risks and create follow-up Issues for deferred work.
4. Return the Issue URL, PR URL, merge result, validation summary, and remaining work.

## Update documentation

Update docs immediately when changes affect public commands/options, storage layout, schema or wire format, migration behavior, defaults, security/safety boundaries, operational sequence, or user-visible status semantics. Describe the current implementation, not the history of review fixes.

After every two completed, non-shelved feature Issues, perform a documentation checkpoint: refresh roadmap/status docs, show the current observable effect, reconcile related Issues, and report what is ready next. Documentation-only or shelved privacy work does not count unless the user says otherwise.

## Stop conditions

Stop and report instead of guessing when:

- when attempting merge or opening an upstream PR, the required explicit authorization is missing;
- when attempting report generation, staging, or merge, `explain-diff-for-human-review` is unavailable or its required review artifact cannot be produced;
- when declaring readiness, staging, or merging, the current HEAD has no completed Codex GitHub review, even if the request was acknowledged or the wait timed out;
- automatic staging reaches a risky report, conflicting/ambiguous PR stack, completed vision, or empty actionable Issue queue;
- checks are failing or review feedback remains unresolved;
- credentials, permissions, branch protection, conflicts, or external coordination block progress;
- the next action materially expands the approved scope.

When stopped, report current Issue/PR links, exact HEAD, completed checks, blockers, and the smallest decision needed to continue.
