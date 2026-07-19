# Diff evidence contract

Read this reference when selecting evidence mode or counting staged, working-tree, unavailable, or omitted material.

## Evidence modes

`immutable-git` applies only when every reviewed byte is represented by an immutable head commit. GitHub reports use the pinned `base_sha...head_sha` compare and `head_sha` file/line permalinks, and never embed raw diff, patch, or hunks.

`mutable-local-snapshot` applies to staged and working-tree targets. Run `scripts/capture_git_snapshot.py` and record its `base_sha`, current `head_sha`, `snapshot_id`, target kind, statistics, `permalink_gap_paths`, and metadata-only paths. The `sha256:` identity binds the exact local Git diff, included untracked or explicitly scoped ignored bytes, and effective generated-path classifications without printing source bytes. It is locally reproducible while that checkout state and classification input still exist; it is not a source permalink or an uploaded archive.

For GitHub mutable targets, pass the helper's `permalink_gap_files` to `classify_diff_size.py`. Any non-zero gap returns `fixed_compare_covers_target=false`; zero gap means the target content is already represented by `HEAD`. A `base_sha...HEAD` link may describe a committed subset only when non-empty and must be labeled as partial coverage. It never covers paths in `permalink_gap_paths`. A clean snapshot with no changed paths is complete zero-change evidence; a zero-diff compare is never evidence for a non-clean snapshot.

Do not commit, push, upload, mirror, or otherwise publish local material merely to manufacture permanent links.

## Target and counting rules

Count each repository-relative target path once. `staged` includes the index relative to the selected base and excludes unstaged, untracked, and ignored material. `working-tree` includes the final tracked state plus non-ignored untracked files; ignored files remain outside the target unless the user explicitly names them.

`changed_lines` is additions plus deletions from Git numstat for tracked text. For untracked UTF-8 text without NUL bytes, count physical lines as additions. An unknown line count contributes zero to the aggregate but remains unknown in the path record; never present it as a confirmed zero-line change.

`patch_bytes` is the byte length of the exact local `git diff --binary --full-index --no-ext-diff --no-textconv` material plus the raw byte lengths of included untracked or explicitly scoped ignored files. The helper hashes these bytes and emits only their aggregate size and metadata, not their contents.

| Material | Files | Lines | Bytes | Coverage and disclosure |
| --- | --- | --- | --- | --- |
| Committed or mutable tracked text | Count | Git numstat | Count captured diff bytes | Line-reviewable locally; GitHub permalinks cover it only when it exists at `head_sha`. |
| Staged text | Count in `staged` and `working-tree` | Git numstat | Count | Add path to `permalink_gap_paths`; GitHub evidence is incomplete until committed. |
| Untracked text | Count only in `working-tree` | Physical UTF-8 lines | Count raw bytes | Local lines may inform analysis, but the HTML omits source and discloses the permalink gap. |
| Binary | Count | Unknown | Count captured bytes | Metadata-only; increment unavailable patches, list the path and reason, and set local line evidence incomplete. |
| Generated/vendor | Count when in target | Count only when deterministic textual stats exist | Count | Metadata-only even when line counts exist; increment unavailable patches and disclose the classification source. Pass known paths with `--generated-path`. |
| Submodule gitlink | Count | Unknown | Count captured diff bytes | Detect Git mode `160000`; treat the commit-pointer change as metadata-only and increment unavailable patches. Never interpret numeric numstat as reviewed source lines. |
| Ignored | Exclude by default | Exclude | Exclude | State the default exclusion. If the user explicitly scopes an untracked ignored file, pass `--include-ignored-path`, then count it by the untracked rules and mark status `!`. Reject tracked paths so one path cannot enter the inventory twice; never enumerate ignored paths speculatively. |
| Missing patch or material | Count when the target inventory proves the path | Count only known stats | Count only received bytes | Increment unavailable patches, identify the path as missing, and set evidence incomplete. Do not silently fall back to another version. |
| Truncated patch or material | Count | Count only verified complete stats | Count only received bytes | Increment unavailable patches, record the truncation boundary and omitted remainder, and set evidence incomplete. |

Binary, generated/vendor, submodule, missing, and truncated paths appear in the metadata-only or omission disclosure even when their byte size is known. `local_evidence_complete` describes line-level local coverage only. Final report `evidence_complete` additionally incorporates hosting coverage: a non-clean GitHub mutable target is incomplete because immutable links do not cover its local paths.

## Snapshot helper

Example:

```bash
python scripts/capture_git_snapshot.py \
  --repository <repo> \
  --target-kind working-tree \
  --base HEAD \
  --generated-path path/to/generated.js
```

The helper captures twice and fails if the material changes between reads. Its JSON is metadata-only and safe to store beside the report, subject to the repository paths already being in review scope. Re-run it immediately before finalizing the report; if the identity changes, discard conclusions bound to the earlier snapshot.
