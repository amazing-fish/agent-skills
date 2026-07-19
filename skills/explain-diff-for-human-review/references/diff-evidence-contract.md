# Diff evidence contract

Read this reference when selecting evidence mode or counting staged, working-tree, unavailable, or omitted material.

## Evidence modes

`immutable-git` applies only when every reviewed byte is represented by an immutable head commit. GitHub reports use the pinned `base_sha...head_sha` compare and `head_sha` file/line permalinks, and never embed raw diff, patch, or hunks.

`mutable-local-snapshot` applies to staged and working-tree targets. Run `scripts/capture_git_snapshot.py` and record its `base_sha`, current `head_sha`, `snapshot_id`, target kind, `scope_paths`, statistics, `permalink_gap_paths`, and metadata-only paths. The `sha256:` identity binds the streamed local Git diff digest, exact bytes for line-reviewable untracked or explicitly scoped ignored files, metadata descriptors for material that must not be read as source, and effective scope/generated-path classifications without printing source bytes. It is locally reproducible while that checkout state and classification input still exist; it is not a source permalink, an uploaded archive, or a content hash for metadata-only LFS objects and nested repositories.

For GitHub mutable targets, pass the helper's `permalink_gap_files` to `classify_diff_size.py`. Any non-zero gap returns `fixed_compare_covers_target=false`; zero gap means the target content is already represented by `HEAD`. A `base_sha...HEAD` link may describe a committed subset only when non-empty and must be labeled as partial coverage. It never covers paths in `permalink_gap_paths`. A clean snapshot with no changed paths is complete zero-change evidence; a zero-diff compare is never evidence for a non-clean snapshot.

Do not commit, push, upload, mirror, or otherwise publish local material merely to manufacture permanent links.

## Target and counting rules

Count each repository-relative target path once. `staged` includes the index relative to the selected base and excludes unstaged, untracked, and ignored material. `working-tree` includes the final tracked state plus non-ignored untracked files; ignored files remain outside the target unless the user explicitly names them. Preserve a non-add/delete mode or file-type change held only by the index when filesystem mode resolution omits that path from the `working-tree` final-content diff, but never overwrite a final mode/type that the working-tree raw inventory observed. For a file- or directory-scoped review, pass each literal scope with `--path`. Convert native backslash separators only on Windows; on POSIX, preserve backslashes and drive-like colons as literal filename characters. Patch, uncommitted, and untracked inventories use that scope so unrelated local path names and bytes cannot affect the snapshot or its identity. Rename/copy discovery scans relationship metadata before filtering; when either endpoint is in scope, preserve the one relationship and derive an effective scope containing both endpoints for patch identity, uncommitted gaps, and permitted untracked evidence rather than degrading the relationship to add/delete or losing later counterpart changes.

`changed_files` is base-relative, while `permalink_gap_paths` is HEAD-relative. Keep these dimensions separate: when a local edit restores a HEAD-changed path exactly to the selected base, the target has no base-relative changed file but still has one mutable path that a `head_sha` permalink cannot represent. Therefore `permalink_gap_files` may exceed `changed_files`; pass both values unchanged to the classifier so it keeps `fixed_compare_covers_target=false`.

`changed_lines` is additions plus deletions from Git numstat for tracked text. For untracked UTF-8 text without NUL bytes, count physical lines as additions. An unknown line count contributes zero to the aggregate but remains unknown in the path record; never present it as a confirmed zero-line change.

`patch_bytes` is the byte length of the exact local `git diff --binary --full-index --no-ext-diff --no-textconv` stream plus known byte lengths of included untracked or explicitly scoped ignored material. The helper streams the diff and ordinary files through bounded buffers. For metadata-only LFS objects it uses filesystem size without reading object contents; for nested repository directories the byte length remains unknown and contributes zero. The helper emits only aggregate size and metadata, not source contents.

| Material | Files | Lines | Bytes | Coverage and disclosure |
| --- | --- | --- | --- | --- |
| Committed or mutable tracked text | Count | Git numstat | Count captured diff bytes | Line-reviewable locally; GitHub permalinks cover it only when it exists at `head_sha`. |
| Staged text | Count in `staged` and `working-tree` | Git numstat | Count | Add path to `permalink_gap_paths`; GitHub evidence is incomplete until committed. |
| Untracked text | Count only in `working-tree` | Physical UTF-8 lines | Count raw bytes | Local lines may inform analysis, but the HTML omits source and discloses the permalink gap. |
| Rename/copy | Count the relationship once at its destination path | Unknown for line coverage | Count captured diff bytes | Preserve the source path and Git status, enable rename and copy detection including unchanged copy sources, classify as metadata-only, and increment unavailable patches. Do not expand a pure relationship into delete/add line counts. |
| Binary | Count | Unknown | Count captured bytes | Metadata-only; increment unavailable patches, list the path and reason, and set local line evidence incomplete. |
| Generated/vendor | Count when in target | Count only when deterministic textual stats exist | Count | Metadata-only even when line counts exist; increment unavailable patches and disclose the classification source. Pass known files or directory roots with `--generated-path`; a directory classification applies recursively to its target descendants. |
| Submodule gitlink | Count | Unknown | Count captured diff bytes | Detect Git mode `160000` with literal target-path probes; treat the commit-pointer change as metadata-only and increment unavailable patches. Never let pathspec metacharacters redirect the probe or interpret numeric numstat as reviewed source lines. |
| Git LFS | Count | Count pointer-line stats when known, never object lines | Count captured pointer/diff bytes or known untracked object size | Detect the `filter=lfs` attribute in the target or base and fail closed if either attribute probe fails. Classify as metadata-only and increment unavailable patches without reading, fetching, hashing, or publishing an untracked LFS object. |
| Lockfile | Count | Count deterministic textual stats when known | Count | Recognize standard ecosystem names (including `npm-shrinkwrap.json`, `go.sum`, and `Package.resolved`) and `.lock`/`.lock.json` suffixes, classify as metadata-only, and increment unavailable patches. |
| Mode or file-type change | Count once | Count textual stats when also present; mode-only numstat is zero | Count captured diff bytes | Preserve old/new Git modes in the path record. When non-add/delete modes differ, classify the entry as metadata-only and increment unavailable patches so executable or type semantics cannot hide behind complete line coverage. |
| Untracked directory or nested repository | Count the disclosed directory path once | Unknown | Unknown | Do not recurse or read repository contents as one file. Bind path/size/time metadata, classify as metadata-only, increment unavailable patches, and state that the snapshot identity does not bind nested contents. |
| Tracked deletion with an untracked replacement at the same path | Count once | Unknown | Count the tracked diff stream plus known replacement size | Coalesce the collision into one `untracked-replacement` metadata-only entry. Do not append a second path record or claim line-level final-state coverage. |
| Ignored | Exclude by default | Exclude | Exclude | State the default exclusion. If the user explicitly scopes an untracked ignored file, pass `--include-ignored-path`, then count it by the untracked rules and mark status `!`. Treat the supplied name literally even when it contains Git pathspec metacharacters. Reject tracked paths so one path cannot enter the inventory twice; never enumerate ignored paths speculatively. |
| Missing patch or material | Count when the target inventory proves the path | Count only known stats | Count only received bytes | Increment unavailable patches, identify the path as missing, and set evidence incomplete. Do not silently fall back to another version. |
| Truncated patch or material | Count | Count only verified complete stats | Count only received bytes | Increment unavailable patches, record the truncation boundary and omitted remainder, and set evidence incomplete. |

Rename/copy, binary, generated/vendor, submodule, Git LFS, lockfile, missing, and truncated paths appear in the metadata-only or omission disclosure even when their byte size is known. `local_evidence_complete` describes line-level local coverage only. Final report `evidence_complete` additionally incorporates hosting coverage: a non-clean GitHub mutable target is incomplete because immutable links do not cover its local paths.

## Snapshot helper

Example:

```bash
python scripts/capture_git_snapshot.py \
  --repository <repo> \
  --target-kind working-tree \
  --base HEAD \
  --path path/to/reviewed-area \
  --generated-path path/to/generated.js
```

The helper captures repeatedly and fails if bound material changes between reads. Its snapshot identity binds the scoped patch digest, filtered relationship/numstat and old/new mode metadata, tracked material classifications (including LFS attribute results), ordinary untracked bytes, and disclosed metadata-only descriptors. It streams patch and ordinary-file hashing in bounded chunks, and it re-resolves `HEAD^{commit}` after the final capture to fail on HEAD-only drift. Metadata-only LFS objects and nested repositories are represented by disclosed filesystem metadata rather than content hashes, so their line-level evidence remains incomplete. Its JSON is metadata-only and safe to store beside the report, subject to the emitted scope and any cross-scope relationship counterpart already being appropriate to disclose. Re-run it immediately before finalizing the report; if the identity changes, discard conclusions bound to the earlier snapshot.
