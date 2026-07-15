---
name: execute-github-issue-pr-workflow
description: Execute a lightweight governed GitHub Issue-to-PR delivery loop with focused implementation, clickable commit and PR links, one-shot 6-minute Codex review checks, comment resolution, human-readable diff evidence, controlled merge or staging, Issue reconciliation, and documentation updates. Use when repeatedly advancing repository Issues, shepherding PRs, handling Codex feedback, or following the user's established GitHub workflow.
---

# Execute GitHub Issue–PR Workflow

Treat GitHub remote state as authoritative. Preserve unrelated work and never commit directly to the default branch.

## Establish scope and mode

1. Inspect repository instructions, ownership, default branch, working tree, relevant Issues/PRs, checks, and docs.
2. For a user-owned repository, create a ready-for-review PR without extra approval. For external upstreams, work only in the user's fork and obtain approval before creating an upstream Issue, opening a Draft upstream PR, or otherwise contacting maintainers.
3. Reuse an existing Issue when it covers the work; otherwise create one before non-trivial implementation where authorized. Keep scope and acceptance criteria bounded.
4. Use neutral links such as `Refs #N` unless automatic Issue closure is explicitly authorized.
5. Use default approval mode unless the user explicitly enables automatic staging mode:
   - **Default:** stop after review and diff evidence; merging requires a later explicit approval for the current PR and exact HEAD, and only then may the next Issue start.
   - **Automatic staging:** a reviewed low-risk PR stays open and unmerged while the next Issue starts. Branch independent follow-ups from the current default branch; stack only genuine dependencies and record their order. Stop for human direction when risk appears, PRs conflict, the vision is complete, or the actionable queue is empty.

## Implement and publish

1. Branch from the current base and implement only the Issue acceptance criteria.
2. Add focused tests and update affected docs. Run the relevant tests, lint, and type checks; record commands, results, and any unavailable checks.
3. Commit and push focused changes. Immediately return a full clickable URL for every pushed commit: `https://github.com/<owner>/<repo>/commit/<sha>`.
4. Open or update a concise PR with the linked Issue, purpose, changes, exclusions, risks, validation, and screenshots when useful.
5. Immediately return the full clickable PR URL after creation or material update.
6. Never merge a PR in the same assistant turn that created it. A timer or auto-merge setting cannot bypass this boundary.

## Check Codex Review efficiently

For each new ready-for-review PR HEAD:

1. Record the PR URL, HEAD, and existing Codex 👍 reactions; previous reactions are stale for this cycle. Then set exactly one **one-shot 6-minute timer**. Do not poll while it is active.
2. When it fires, refresh the PR once. If HEAD differs from the recorded HEAD, discard this cycle, snapshot reactions again, and start one new timer. Otherwise read the Codex state or reactions on the PR body, review decisions including requested changes, conversation and inline comments, unresolved threads, checks, and mergeability.
3. Classify that single refresh:
   - **Passed:** a new 👍 from the repository's Codex bot on the PR during this cycle is sufficient. Do not require a commit review, `commit_id`, or SHA binding. Continue only if no actionable feedback or relevant failed check remains; document any explicit check waiver.
   - **In progress:** do not mention the bot again; set one new one-shot 6-minute timer.
   - **Not triggered:** post `@codex review` once for this review cycle, return the comment URL, then set one new one-shot 6-minute timer.
   - **Findings or failures:** fix in scope issues on the same branch, test, push, return the new commit URL, and start a fresh one-shot 6-minute review cycle.
4. Never poll every minute or infer success from elapsed time, silence, or acknowledgement alone.
5. If waiting cannot continue in the current environment, report `Codex review pending` with the PR URL, HEAD, current robot state, and the next refresh time, then stop cleanly.

## Resolve findings

- Fix small in-scope findings at their root and add focused regression coverage.
- Split risky or scope-changing work; create a follow-up Issue for architectural or out-of-scope findings.
- Resolve threads only after the fix or rationale is verified. Re-check current comments, checks, conflicts, acceptance criteria, and docs before declaring readiness.

## Gate merge or staging

Require all of the following:

- acceptance criteria and all relevant checks pass or have an explicit documented waiver;
- the current review cycle receives a new Codex-bot 👍 on the PR;
- no blocking review decision, unresolved feedback, conflict, or scope decision remains;
- validation and docs match the current code;
- the installed `explain-diff-for-human-review` skill produces a report for the current diff.

In default mode, present the report for the current HEAD and request approval naming that PR and HEAD; any HEAD change invalidates the report and approval. Merge only in a later user turn. In automatic staging mode, stage only when the report says `可以合入` with no confirmed medium-or-higher risk or unresolved decision. Automatic staging never authorizes merging.

Immediately before an authorized merge, require HEAD to equal the reported and approved HEAD, then recheck PR state, checks, threads, and mergeability. Never bypass protection or force-push.

## Reconcile and continue

1. If merged, verify it landed and return clickable PR and merge-commit URLs. If staged, keep the PR unmerged and record its URL, exact HEAD, and dependencies.
2. Close or update the Issue only for landed work and within the user's authorization; keep staged Issues open. Return the Issue URL and residual work.
3. Update docs when commands, contracts, schemas, defaults, operations, safety boundaries, or user-visible behavior change.
4. After every two merged feature Issues, or two staged feature Issues in automatic staging mode, refresh roadmap/status docs and reconcile related Issues. Label unmerged work as `staged` and link its PR and exact HEAD.
5. Stop instead of guessing when authorization, the diff skill, review success, checks, permissions, conflicts, credentials, or a material scope decision blocks progress.
