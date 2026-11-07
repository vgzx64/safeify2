# Transition dataset pilot — results

> **Status: pilot · 2026-10-24 · Not a frozen dataset**
>
> Design: [transition dataset plan](transition-dataset.md)
> Pipeline: [research/transitions/README.md](../../research/transitions/README.md)

## Question

Can a fresh pass over `CVEfixes.db` and the cloned repositories produce a
better positive/negative pool than the RQ4 manifest?

RQ4 was extracted under deadline pressure and is not reliable: 114 rows, all
`converted_to_safe=1`, from 29 CVEs; 56/114 come from two CVEs. Of its 80
pair-text rows, 36 have no safe snippet and 2 have a "safe" snippet that still
contains `unsafe`. Its label is function-level: "the containing function has no
unsafe blocks after the fix."

## Data actually used

| Item | Count |
|---|---:|
| Fix commits in `commits` | 742 |
| Distinct CVEs in `commits` | 576 |
| Distinct repositories | 382 |
| `file_change` rows with a diff | 3,255 |
| Distinct vulnerable unsafe blocks | 64,254 |
| Distinct fixed unsafe blocks | 64,380 |

The database documentation says 433 vulnerabilities / 300 repositories / 218
fix commits; the actual tables are larger. The current tables are the source of
truth for this analysis.

Parent commits come from `ext_commits`, not `git rev-parse <hash>^`. File
snapshots come from `repos_mirror/<owner>_<repo>` with
`git show <rev>:<path>`.

## Method

### Analyzer-first (`extract_candidates.py`)

1. Start from a distinct `unsafe_block` key.
2. Keep it only if the exact key is absent from `unsafe_block_fix` while the
   same `(cve, hash, fn_id, path)` function is still present.
3. Load the real parent and fix file snapshots.
4. Reject if the old block text still appears in the fixed file. This caught
   **888** blocks whose analyzer span moved but whose code was retained.
5. Require a diff hunk that overlaps the block and fully deletes the old text.
6. Classify the added lines as safe, still-unsafe, or empty.

### Diff-first (`mine_diff.py`)

1. Parse every `file_change.diff` hunk.
2. Keep hunks whose deleted lines contain a concrete `unsafe { ... }`,
   `unsafe fn`, or a known unsafe API.
3. Isolate a window around the unsafe deletion; do not trust the whole hunk.
4. Validate deleted/added lines at their diff line numbers. Deleted lines in a
   hunk are not contiguous in the parent, so joined-text substring matching was
   rejecting valid hunks.
5. Classify as `diff_safe`, `diff_unsafe`, or `diff_removed`.

### Pattern pass (`mine_patterns.py`)

Targeted matches for `set_len`, `uninit`/`assume_init`, `get_unchecked`,
`from_raw*`, `ptr::read`/`write`, `copy*`, `write_bytes`,
`Pin::new_unchecked`, and `transmute`. A residual `unsafe` block or unsafe call
makes the result `conditional`, not safe.

## Data recovery

### PR-URL normalization

Many `commits.repo_url` values are pull-request URLs such as
`https://github.com/google/flatbuffers/pull/7518`. The old mapper produced
`pull_7518`, which does not exist in `repos_mirror`. Normalizing `/pull/<n>`,
`/issues/<n>`, `/commit/<sha>`, `/tree/...`, and `/blob/...` to the repository
root recovered those snapshots.

### Line-number validation

The first diff pass required the joined deleted text to be a substring of the
parent file. That is wrong when a hunk has multiple deletion regions: the
deleted lines are not contiguous. Switching to per-line validation at the diff
line numbers recovered another large batch.

| Metric | Initial | PR-URL fix | Line validation |
|---|---:|---:|---:|
| Diff candidates | 159 | 277 | **433** |
| Merged candidates | 183 | 300 | **454** |
| Clear positives | 38 | 44 | **74** |
| Missing before/after snapshots | 496 | 76 | **50** |

These were not new CVEs. They were already in CVEfixes, hidden by URL mapping
and a too-strict alignment check.

## Results

| Method (merged) | Candidates | Safe | Conditional | Unsafe | Removed |
|---|---:|---:|---:|---:|---:|
| Analyzer-first | 57 | 4 | 0 | 52 | 1 |
| Diff-first | 392 | 86 | 1 | 295 | 10 |
| Pattern pass | 5 | 0 | 5 | 0 | 0 |
| **Total** | **454** | **90** | **6** | **347** | **11** |

The analyzer-first rejects account for all 1,113 non-exact blocks: 888 retained
text, 114 function removed or not analyzed, 48 old block not fully deleted, 4
no deleted lines.

The targeted pattern pass produced 44 rows, but most duplicate an existing
function; only five are new, all conditional. They retain
`ptr::copy_nonoverlapping`, `ptr::write`, or `from_raw_parts_mut`. The pattern
pass adds **no clear positives**.

## Safe-candidate audit

All 90 safe rows were reviewed from the old/new snippets and source context.
Labels:

| Label | Count | Meaning |
|---|---:|---|
| `safe_replacement` | **74** | a concrete safe replacement or safe guard replaces the unsafe operation |
| `unclear` | 6 | hunk mixes unrelated changes; pair is not clean |
| `false_positive` | 7 | `unsafe` in a comment, a truncated signature, or an unrelated hunk |
| `signature_change` | 1 | `unsafe fn` -> `fn`; a contract change, not a block replacement |
| `duplicate` | 2 | same fix as another reviewed row |

The 74 clear positives span **32 CVEs, 27 repositories, and 32 fix commits**.
This is not 90: duplicates, false positives, and signature-only changes must not
be counted.

Mechanisms in the 74 clear positives:

| Mechanism | Count | Example |
|---|---:|---|
| checked indexing | 18 | `get_unchecked` / `ptr::read` -> `self.values[id].as_ref().unwrap()` |
| safe helper | 11 | Diesel raw libpq handling -> `rows_affected` / `get_bytes` |
| zero initialization | 8 | `set_len` / `uninitialized` -> `vec![0; n]` |
| pin API | 4 | `Pin::new_unchecked` -> `Pin::from` |
| resize / truncate | 4 | `set_len` -> `resize` or `truncate` |
| safe enum conversion | 4 | `from_bits_unchecked` -> `from_bits_truncate` |
| `RefCell` borrow | 3 | `UnsafeCell` helper -> `borrow_mut` |
| layout change | 3 | uninitialized writes -> iterator/collect |
| remove unnecessary `unsafe` | 3 | `unsafe { safe_call() }` -> `safe_call()` |
| other | 16 | cells, parser, UTF-8, owned Vec, slice, copy |

Representative clear positives:

- `badboy/lzf-rs`: `out.set_len(n)` and `mem::uninitialized()` -> `vec![0; n]`.
- `andrewhickman/id-map`: `get_unchecked` / `ptr::read` -> checked indexing and
  `Option`.
- `actix-net`: `Pin::new_unchecked(...)` -> `Pin::from(...)`.
- `lexical`: `MaybeUninit::uninit().assume_init()` -> `[0u8; N]`.
- `tokio`: raw `UnsafeCell` clone/write -> safe slot clone/assignment.
- `diesel`: raw libpq strings and slices -> safe helper methods.
- `flatbuffers`: `from_bits_unchecked` -> `from_bits_truncate` (generated test
  fixtures; four rows are not four independent patterns).

Syntax gate: **82/90** fixed files parse with the bundled `syn 1.0.72`
extractor. The eight failures are mostly newer syntax, macro/truncated
contexts, or false-positive hunks. This is a syntax check only, not
compilation, tests, or Miri.

## Unsafe-to-unsafe pool

The merged manifest has **347** unsafe-to-unsafe candidates across 71 CVEs, 63
repositories, and 88 commits, plus **6 conditional** rows. Automatic categories
(provisional):

| Category | Count | What it looks like |
|---|---:|---|
| `signature` | 140 | `unsafe impl<T> Send` -> `unsafe impl<T: Send> Send` |
| `guard_or_init` | 38 | adds `assert!`, `resize`, `zeroed`, `catch_unwind` |
| `same_api_refactor` | 30 | same unsafe API, receiver/field renamed |
| `other` | 139 | mixed refactors, type changes, duplicate functions |

The pool is heavily concentrated:

- **127 rows are `google/flatbuffers`; 99 of those are signature-only.**
- `pulse-binding` (27), `wasmtime` (26), `rustix` (23), and `risc0` (20) follow.

Capping to at most three non-signature rows per repository leaves **84 rows
across 45 repositories**. A 28-row stratified sample of that capped pool found:

| Audit label | Count |
|---|---:|
| guard / initialization | 12 |
| refactor with unsafe retained | 15 |
| different unsafe API | 1 |
| hard negative | **0** |

The sample contains **no hard negatives**. The two known hard negatives are from
the older pre-recovery sample (`actix-utils` `Cell` -> `RefCell` while retaining
`get_unchecked_mut`). The 347-row pool is therefore not a negative class; it is
a candidate pool for manual review.

## Zero-shot detector result

The current detector (`--no-lsp`) was run on the 74 clear positives and nine
pre-recovery negative/guard samples:

| Group | Files | No sink | Has Y | Y sinks | M sinks | N sinks |
|---|---:|---:|---:|---:|---:|---:|
| Positives (expected Y) | 74 | 31 | 18 | 27 | 34 | 0 |
| Hard negatives (2) + guards (7) | 9 | 4 | 2 | 2 | 3 | 0 |

- Only **18/74 (24%)** positives get a Y anywhere; **31/74 (42%)** produce no
  sink at all.
- Both hard negatives (`actix-utils` `get_unchecked` / `get_unchecked_mut`) are
  predicted **Y** — the dangerous direction.
- The detector makes **zero N claims** on this set.

This is not a model that can label the dataset. It is a baseline that shows the
distribution shift: the SafeNet-shaped detector does not recognize most
CVEfixes-style transitions.

## Additional sources (2026-10-26)

- **crates.io version pairs**: 200 advisories paired, 872 unsafe-changing
  hunks, 191 safe candidates. A 54-row adjudication gave 23 `Y`, 5 `M`, 3 `N`,
  23 `U`/veto. These rows are included in the 276-row total.
- **official Rust docs / rust-src 1.99.1**: 897 `# Safety` sections, 310 public
  contracts after filtering, 469 doc examples. These are contract/alternative
  data, not transition rows; not yet merged.
- **Rust-for-Linux**: 8 abstraction commits sampled, 3 unsafe-changing hunks
  (2 unsafe-added, 1 retained). No safe-candidate row in the sample; this is an
  `encapsulate` source, not a CVE-positive source.

## LLM adjudication pilot

The curation queue is now separate from the strict miner:

- **772 strict CVEfixes hunks** (after replacing the generic `ptr::deref` /
  `as_ref` heuristics with actual `unsafe` / known-unsafe-API checks):
  121 safe candidates, 366 unsafe-retained, 285 unsafe-added.
- **458 queued rows**: 92 safe candidates and 366 retained-unsafe rows.
- A 30-row pilot was adjudicated with the rubric in
  [adjudication/RUBRIC.md](../../research/transitions/adjudication/RUBRIC.md).

206 CVEfixes + 16 RustSec + 54 crates.io rows were adjudicated:

| Label | Count |
|---|---:|
| `Y` replaceable | 103 |
| `M` conditional/guard | 65 |
| `N` keep | 58 |
| `U` unresolved | 50 |
| vetoed | 48 |

The first 60-row queue was **not** usable: 31/60 were vetoed because the old
`api_guess` matched safe `as_ref`/pointer code. The strict signal fixed that
before scaling. A human spot-check of five Y rows found one clipped-context
overclaim (`crossbeam-epoch` `mem::uninitialized` → `MaybeUninit::uninit` with
later unsafe writes not shown); it was corrected from Y to M.

The LLM `Y` labels are **not** the manual 74-positive set. Matching on
`(commit, path, normalized old text)`:

- manual clear and LLM `Y`: **56 overlap**
- manual-only: **18**
- LLM-only: **16**
- union of CVEfixes positives: **90**

The two tracks have not been reconciled. Adding the 7 RustSec `Y` rows gives
**102 candidate positives** across **94 families**, still below 100. The last
20-row safe batch added 16 `Y` labels but only **one new unique positive**; the
rest duplicated existing families. CVEfixes is saturated for this extraction
scheme.

RustSec adds breadth but not many positives: 1,332 advisories, 469 not in
CVEfixes, 147 PR/commit diffs fetched, 189 unsafe-changing hunks, 39 safe
candidates; after strict dedupe only **12 clean candidates across 6 repos**.
RustSec adjudication produced 6 `Y`, 2 `M`, and 4 `U` from 12 clean
candidates (4 vetoes). Resolving 144 issue URLs added 90 same-repo fixes, 59
hunks, and 4 further clean safe candidates; these are not yet adjudicated. The
combined adjudicated set is **154 rows: 78 Y, 33 M, 25 N, 18 U, 18 vetoed**.

**Only 142/458 CVEfixes queue rows have been adjudicated.** The retained-unsafe
batches added 25 `N`, 8 `M`, and 6 `U`/veto; this is the first meaningful
negative set. The remaining queue is still unlabeled.

## RQ4 comparison

| | RQ4 | This pilot |
|---|---:|---:|
| Candidate rows | 114 | 454 |
| Label scope | function-level | block/hunk-level |
| Positive rows | 114 (all) | 90 safe; 74 reviewed clear |
| Negative rows | 0 | 347 unsafe + 6 conditional (unreviewed) |
| CVEs | 29 | 96 total; 32 with clear positives |
| Concentration | 56/114 from 2 CVEs | 31/74 from id-map + diesel; 127/347 negatives from flatbuffers |
| Pair text | 36/80 missing safe; 2/80 still `unsafe` | every row has old/new text; 74 reviewed clear |
| Syntax gate | none | 82/90 parse |

The new pass is not directly comparable to RQ4. RQ4 counted function-level
conversions; this pilot counts aligned block/hunk transitions and rejects
retained text. The honest comparison is quality, not count.

## Draft core and splits

An unfrozen draft was built from the positive union (112) and negative core (83):

- **231 rows** after dedupe: 118 Y, 57 M, 56 N.
- **97 repositories**, split by repository: 82 train / 71 valid / 78 test.
- The test split has **51 Y + 15 M + 12 N**; the valid split has 31 Y + 17 M + 23 N.

This is too small to support a headline result. It is a schema/split dry run. The
files are `transitions_core_draft.jsonl`, `splits_draft.json`, and
`transitions_core_draft_stats.json`.

## Exploratory v0.1 and gate report

A family-level exploratory core was built by collapsing duplicate
`(repo, path, function)` families:

- **190 rows**: 109 Y, 43 M, 38 N.
- **97 repositories**; split 97 train / 36 valid / 57 test.
- Test: 25 Y + 18 M + 14 N.

The honest gate report is in
`transitions_core_v0.1_quality.json`. The positive-family gate now passes; the
remaining freeze gates fail:

- positive families ≥100: **true** (109)
- negative rows ≥300: **false** (81 after family collapse)
- test rows ≥50: **true** (64)
- queue coverage ≥80%: **false** (206/458)
- manual/LLM tracks reconciled: **false**

Status: **not frozen; exploratory only**.

## Final status (2026-10-26, round 12)

The deliverable is an **exploratory v0.1**, not a frozen final dataset. Round
12 ends blocked on negative and queue coverage:

- `transitions_core_v0.1_exploratory.jsonl`: **190 rows** (109 Y, 43 M, 38 N).
- `splits_v0.1.json`: **97 train / 36 valid / 57 test**.
- Positive-family gate: **pass (109 families)**.
- Test-size gate: **pass (64)**.
- Negative gate: **fail (123 reviewed, <300)**.
- Queue coverage: **fail (206/458)**.
- Manual/LLM reconciliation: **pass** (18 manual-only rows re-adjudicated; 16 kept Y, 2 demoted to M).

crates.io is now the main external positive source: 200 advisories, 872
unsafe-changing hunks, 191 safe candidates, 54 adjudications (23 Y). Official
docs and Rust-for-Linux are separate contract/encapsulation sources.

## Critical assessment

This is **not a final dataset**.

1. **Positive count is no longer the blocker.** 119 rows / 109 families pass the
   gate, but duplicates remain in `id-map`/`diesel`/`smallvec`/crates.io.
2. **Negatives are the blocker.** 123 reviewed vs 300; most retained rows are
   guards or contract changes.
3. **Queue coverage is 45%.** 252 CVEfixes rows remain unlabeled.
4. **The split is uneven.** 97 train / 36 valid / 57 test passes the size gate
   but is not source-balanced enough for a final claim.
5. **Manual and LLM positives are reconciled**, with two disagreements recorded.
6. **crates.io yield is low per advisory.** 200 advisories → 23 Y.
7. **Docs/Rust-for-Linux are not positive padding.** They add `M`/`N`/
   `encapsulate` evidence.
8. **No compile/test/Miri gate**, by design.

## Implication

Use the 111-family v0.1 as an **exploratory seed**, not as the final training
set. The remaining blockers are negative coverage, queue coverage, split
quality, and positive-track reconciliation.

## Next

1. Finish the retained queue toward 300 negatives.
2. Rebuild a source-stratified split with adequate train/valid/test.
3. Reconcile manual and LLM positives.
4. Adjudicate more docs contracts/examples.
5. Freeze only after all gates pass.

## Artifacts

- [Positive union: 121](../../research/transitions/out/positive_union.jsonl)
- [Negative core: 106](../../research/transitions/out/negative_core.jsonl)
- [Family-level v0.1 core: 189](../../research/transitions/out/transitions_core_v0.1_exploratory.jsonl)
- [Quality gates](../../research/transitions/out/transitions_core_v0.1_quality.json)
- [Splits](../../research/transitions/out/splits_v0.1.json)
- [crates.io candidates](../../research/transitions/out/cratesio_candidates.jsonl)
- [Public docs contracts](../../research/transitions/out/docs_public_safety.jsonl)
- [Rust-for-Linux sample](../../research/transitions/out/rust_for_linux_hunks.jsonl)
