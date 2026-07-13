# Repository operating rules

These rules apply to the entire repository.

## Change scope and validation

- Keep every change traceable to an issue or explicit user request.
- Preserve upstream provenance in `sources.lock.json` when modifying an imported Skill.
- Do not mix unrelated cleanup into a focused pull request.
- Validate the affected Skill, its deterministic scripts, tests, links, and generated-output policy before publishing changes.

## Pull request workflow

1. Create a dedicated branch from the current default branch and link the governing issue in the pull request.
2. Include the behavior change, compatibility impact, and exact validation evidence in the pull request body.
3. After opening a pull request, end the current conversational turn with its link, head SHA, and validation status. Do not merge it in that turn.
4. A later conversational turn may merge only when the user explicitly authorizes merging or an already-authorized autonomous workflow includes it.
5. Before merging, re-read the current head SHA, mergeability, checks, reviews, top-level comments, and unresolved review threads. Do not rely on a snapshot taken when the pull request was opened.

A conversational turn begins with a user message and ends with the assistant's final response. Waiting, polling, receiving a fast approval, or enabling auto-merge does not bypass the same-turn merge prohibition. A pull request opened during the current turn is ineligible for both direct merge and auto-merge until a later user turn.

## Review feedback

- Fix actionable review feedback on the existing pull request branch whenever that pull request is open and writable.
- Read the full thread before editing, keep the fix traceable to the comment, and push the smallest coherent update to the same head branch.
- After validation, reply in the original thread with the fix commit and test evidence, then resolve the thread when the feedback is fully addressed.
- Re-read checks, reviews, comments, and unresolved threads after every feedback update. Earlier approvals or mergeability results may no longer be current.
- Do not open a follow-up pull request merely because review feedback arrived after the first push.

A follow-up pull request is allowed only when the original pull request is already merged or closed, its head branch is not writable, or the requested work is materially outside the original scope. State the reason and link both pull requests when using an exception.

## Merge safety

- Merge only the reviewed head SHA; stop if the head changes unexpectedly.
- Do not merge with failing or pending required checks, unresolved actionable threads, requested changes, or an unclear merge state.
- After merging, verify the default branch contains the intended files and that linked issues have the expected state.
