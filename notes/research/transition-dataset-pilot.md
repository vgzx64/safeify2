# Transition dataset pilot — results

> **Status: v0.2 FROZEN · 2026-11-08 · 433 rows; split leakage 0; blind spot-checks pass on the binary target; M/N retained as descriptors only**
>
> Design: [transition dataset plan](transition-dataset.md)
> Pipeline: [research/transitions/README.md](../../research/transitions/README.md)
> Pair model: [bert-pair-model.md](bert-pair-model.md)

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
  23 `U`/veto. These rows are included in the round-12 276-row total.
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

## Gate-closing run (2026-11-07, round 13)

The 12-round budget ended blocked, so the follow-up was scoped to close the two
failing gates instead of labeling the whole remaining pool. Two selections were
built with `adjudication/build_batches.py`:

- **Batch A**: 161 unreviewed CVEfixes queue rows spanning all 118 remaining
  families (one row per family first), to lift queue coverage.
- **Batch B**: 170 untouched crates.io/RustSec retained families (one row per
  family), to add hard-negative families.

Eleven LLM batches (27-29 rows each) were adjudicated against
[`RUBRIC.md`](../../research/transitions/adjudication/RUBRIC.md), merged with
strict id-set validation, and QC'd for evidence quotes and Y-with-unsafe-new.
One new Y claim (RUSTSEC-2021-0144 pointer cast) was demoted to `M` on
spot-check because the shown cast keeps `T: ?Sized`; the correction is recorded
in `out/spotcheck_gate.json`.

Result: **607 reviewed rows** (+331), 76 vetoed. Labels: 104 `Y`, 166 `M`,
259 `N`, 78 `U`. The negative core grew to 425 rows (259 `N` / 166 `M`); the
positive union is 120 rows / 110 families.

## v0.2: draft, label verification, freeze

The draft collapsed families to 435 rows (110 Y / 194 N / 131 M) across 154
canonical repositories, split 218 train / 87 valid / 130 test.

Verification then changed two labels and dropped one row (below), giving the
frozen core `out/transitions_core_v0.2.jsonl`:

- **433 rows**: 109 Y, 193 N, 131 M; 109 positive families.
- **154 canonical repositories**; split 216 train / 87 valid / 130 test
  (49.9 / 20.1 / 30.0), positives 54 / 22 / 33 (50/20/30).
- Valid: 22 Y + 36 N + 29 M; test: 33 Y + 39 N + 58 M.
- Binary target for training: `safe_replaceable` (Y = 1, M/N = 0);
  109 positive / 324 negative rows.

All eight gates pass in `out/transitions_core_v0.2_quality.json`:

- positive families >= 100: **true** (109)
- negative rows >= 300: **true** (324)
- test rows >= 50: **true** (130)
- queue coverage >= 80%: **true** (367/458 = 80.1%)
- manual/LLM tracks reconciled: **true**
- split leakage zero: **true**
- blind spot-check binary agreement >= 85%: **true** (95.2% over 83 rows)
- blind spot-check binary kappa >= 0.60: **true** (0.818)

### Second and third spot-checks (2026-11-08)

An independent annotator relabeled a blind 36-row sample (12 Y / 12 M / 12 N,
all sources) against `RUBRIC.md`. After the corrections below it agrees on
31/35 decidable rows (88.6%), kappa 0.83 three-class, 91.4% binary.

That pass exposed the `M` boundary: 7/12 `M` agreed, and every disagreement was
the same failure (the second annotator read a retained unsafe call as `N`, or a
`Y` where unsafe remained). A focused, fresh 24-row `M`/`N` sample followed.
Pass A agreed on all 12 `M` rows but only 5/12 `N` rows: 70.8% raw, kappa 0.42.
Every disagreement was the "guard/restructuring vs keep" line -- adding
`T: Send` bounds, turning a function into `unsafe fn`, threading an alignment
field into the same `from_raw_parts`.

Rules 9 and 10 were added to the rubric (M needs a quotable check or enforced
precondition; when torn, choose N) and the same 24 rows were relabeled blind by
a fresh annotator: 75% raw, kappa 0.52. The residual disagreements flipped both
ways (`memoffset` `field_check!` added, `rusqlite` length-bounded
`from_raw_parts`), so the boundary is genuinely fuzzy, not just under-specified.

Conclusion: **Y vs not-Y is reproducible (95.2% binary agreement, kappa 0.818
over 83 rows); M vs N is not (kappa 0.42-0.52).** The dataset therefore trains
and evaluates a binary target, `safe_replaceable` (Y vs M+N). `M` stays in the
schema as a descriptor of "guard or restructuring required" and must not be
used as a training class or reported as a three-class accuracy.

### Corrections applied

`adjudication/corrections.jsonl`, applied by `rebuild_v01.py` and
`build_family_core.py`:

| Row | Change | Reason |
|---|---|---|
| `rustsec:RUSTSEC-2026-0300:src/skip_map/filter.rs` | `M` -> drop (`U`) | clipped to a bare `unsafe {` and an argument fragment |
| `cratesio:RUSTSEC-2020-0045:actix-utils:...:src/oneshot.rs` | `N` -> `M` | borrow/length guard added, `get_unchecked_mut` remains |
| `hunk:675:...:src/unix.rs` | `Y` -> `M` | `ptr::write` replaced but `mremap`/`from_raw_parts` remain |

### Canonical identity and split leakage (2026-11-07)

The previous split key was `repo_name`, which differs per source: CVEfixes stores
`owner_repo`, crates.io stores a package name, RustSec stores a fix URL. The
same repository could therefore land on both sides of the split.

`repo_identity.py` now resolves every row to `host/owner/repo`, trying in order:
CVEfixes `repo_url`; RustSec fix/issue URL; current crates.io `repository`
metadata (cached in `out/repo_identity.json`); the historical `Cargo.toml` in
the mined version tarball; then a `pkg:`/`name:` fallback. Current crates.io
metadata is what follows repository moves such as
`jgallagher/rusqlite` -> `rusqlite/rusqlite` and
`rust-lang-nursery/futures-rs` -> `rust-lang/futures-rs`.

Result:

- 189 source-level names collapse to **154 canonical repositories**; 30 alias
  groups merge, including `servo_rust-smallvec`/`smallvec`,
  `image-rs_image`/`image`, `Amanieu_parking_lot`/`lock_api`,
  `google_flatbuffers`/`flatbuffers`.
- `check_split_leakage.py` reports **0 cross-split duplicate groups** and
  **0 repo/commit/CVE overlap** on every split pair
  (`out/split_leakage.json`).
- 3 rows keep a fallback identity (`torvalds_linux`, `abox`, `atom`); none
  collide across sources.
- Splits were regenerated on canonical keys with whole repositories as the
  unit. Repos are placed positive-first into the split with the largest
  positive deficit that still has row capacity, so both rows and positives land
  near 50/20/30 (218/87/130 rows, 55/22/33 Y). The split is not
  source-stratified: every split contains CVEfixes, crates.io and RustSec rows,
  but the source mix is not forced.
- `train_model.py` (2026-11-07) is the training harness; `research/synth`
  remains the synthetic pretraining corpus and `research/gnn` is still an
  unwired prototype.

### Baseline smoke test (2026-11-07)

`baseline_tfidf.py` trains a char TF-IDF + logistic-regression classifier on
`old_snippet` only (binary `Y` vs `{N,M}`) and evaluates `valid`; the test split
is untouched.

| Metric | Value |
|---|---:|
| Train rows / positives | 218 / 55 |
| Valid rows / positives | 87 / 22 |
| Accuracy | 0.759 |
| Majority accuracy | 0.747 |
| Precision (Y) | 0.538 |
| Recall (Y) | 0.318 |
| F1 (Y) | 0.400 |
| ROC AUC | 0.665 |
| Confusion (tn/fp/fn/tp) | 59 / 6 / 15 / 7 |

Reading: a snippet-only linear model is marginally above the majority class
(+1.2 pp) with weak ranking (AUC 0.67), so the labels carry little signal in the
raw hunk text alone. That is a real result, not a bug: deciding whether unsafe
code is replaceable needs API/safety-contract context, which is exactly the
retriever+classifier design. It is a smoke test on 87 rows, not a model-quality
claim. Test is reported only after freeze.

### First training run (2026-11-07)

`train_model.py` is the first supervised training harness. It compares two
inputs on the same model (char TF-IDF + logistic regression), with grouped
5-fold CV on `train` (groups = canonical repository) and then a held-out check
on `valid`. The context input is a 60-line window of the pre-fix file around the
hunk, recovered from the repo mirrors / crate tarballs (400/435 rows of the
pre-freeze draft; all crates.io rows, 247/253 CVEfixes; RustSec has no snapshot
and falls back to the snippet). The cache predates the freeze and is named after
the frozen version only for convenience.

| Input | CV pooled AUC | CV F1 (Y) | Valid AUC | Valid F1 (Y) |
|---|---:|---:|---:|---:|
| old snippet | 0.831 | 0.714 | 0.665 | 0.400 |
| snippet + 60-line context | 0.780 | 0.558 | 0.388 | 0.176 |

Valid AUC by source (snippet model): CVEfixes 0.635 (46 rows / 16 Y), crates.io
0.911 (33 / 3), RustSec 0.333 (8 / 3). The crates.io and RustSec numbers rest on
3 positives each and are not interpretable.

Reading: grouped CV says 0.83 AUC, but the same model drops to 0.665 on repos it
has not seen. The context window makes it worse (0.39), so raw neighbouring code
is mostly repository-specific noise at this sample size. A shallow snippet
signal survives, but it is not enough for a model claim: 55 training positives
across 43 repositories set the ceiling. Training is not the bottleneck yet;
labels and positives are. The test split was not evaluated.

## Critical assessment

1. **Positives pass but are small.** 109 families, 109 rows: 68 manual + 41
   LLM-only. Duplicates remain in id-map/diesel/smallvec/crates.io.
2. **Negatives pass but are concentrated.** 324 rows across 128 canonical
   repos, but google/flatbuffers alone is 57 rows (17.6%) because its
   `fn` -> `unsafe fn` lint refactor produced many near-identical `N` rows.
3. **Queue coverage is 80.1%**, one row over the line; 91 CVEfixes queue rows
   remain unlabeled.
4. **Split leakage is fixed.** Canonical `host/owner/repo` keys merge 30 alias
   groups and collapse 189 names to 154 repositories; the audit reports 0
   cross-split duplicate groups and 0 repo/commit/CVE overlap.
5. **Split proportions match the target** (218/87/130 rows = 50.1/20.0/29.9;
   positives 55/22/33 = 50/20/30). The split is by whole repository, so a
   hunk-heavy repo can still dominate (flatbuffers is 18.2% of negatives).
   It is label-stratified, not source-stratified; every split has all sources
   but the mix is not forced.
6. **Labels are semantic LLM decisions**, verified by two independent blind
   spot-checks and one focused re-label (5 corrections in total, 3 this round),
   with no compile/test/Miri gate by design. Y vs not-Y reproduces; M vs N does
   not, so only the binary target is used.
7. **crates.io remains low-yield**: 200 advisories -> 23 `Y`; the 170 new rows
   came from version-pair retained hunks, not new positives.
8. **RustSec/OSV/GHSA aliases** are covered by CVEfixes/RustSec; there is no
   separate artifact.
9. **No date cutoff** was applied; dates are used only for evaluation holdouts.
10. **Training transfer gap.** Grouped CV reaches 0.831 AUC but held-out repos
    drop to 0.665; a raw 60-line context window drops further to 0.388. With 54
    training positives spread over 22 of the 42 training repositories, no
    one-sided trained model is trustworthy yet; that is why the next model trains on synthetic pairs and
    treats this core as external validation.

## Implication

v0.2 is frozen: 433 rows, 154 repositories, zero split leakage across eight
gates, and a label target that two independent annotators can reproduce. The
first training run showed the real bottleneck is data, not code: grouped CV
overstates transfer (0.831 -> 0.665 AUC), a raw surrounding-code window makes it
worse (0.388), and 54 training positives cannot support a neural encoder or a
credible one-sided claim.

The verification also changed the target. A three-class scheme (Y/M/N) is not
reproducible, because the M/N boundary is a judgment about how much
restructuring counts; the binary "is there a safe replacement" question is. The
dataset now trains that binary question, which is also the decision NIRM 4
actually needs.

## Next

1. **Train the pair classifier** on `research/synth/out/train_mixed.csv`
   (8,580 clean SafeNet-style pairs after the 2026-11-18 rebuild; valid/test
   excluded, `splits/check_train_leakage.py` passes), using this frozen core as
   external validation on `(old, fix)` pairs. This is the next milestone; see
   the [pair-model plan](bert-pair-model.md).
2. Evaluate the pair model on the frozen valid split (22 Y / 36 N / 29 M) and
   report binary metrics only; keep the test split sealed. Note that the synth
   pair valid set is only 10 pairs (5 pos / 5 neg), so it is a weak selection
   signal; use grouped CV on train for tuning.
3. Build API/contract retrieval features (docs `# Safety` clauses, mechanism
   class) for the retrieval half; the raw context window failed the transfer
   check.
4. Cap per-repo family weight (flatbuffers is 17.6% of negatives) for a
   balanced v0.3.
5. Grow the positive pool: 109 rows is enough to validate, not to train.
6. Finish the 91 remaining CVEfixes queue rows (optional; coverage passes).
7. Keep evaluation holdout dates separate from training collection.

## Artifacts

- [Positive union: 119](../../research/transitions/out/positive_union.jsonl)
- [Negative core: 425](../../research/transitions/out/negative_core.jsonl)
- [v0.2 frozen core: 433](../../research/transitions/out/transitions_core_v0.2.jsonl)
- [Quality gates and label verification](../../research/transitions/out/transitions_core_v0.2_quality.json)
- [Freeze manifest (sha256)](../../research/transitions/out/manifest_v0.2.json)
- [Label reliability report](../../research/transitions/out/label_reliability.json)
- [Reviewer corrections](../../research/transitions/adjudication/corrections.jsonl)
- [Splits](../../research/transitions/out/splits_v0.2.json)
- [Batch manifest](../../research/transitions/adjudication/gate_batches.json)
- [Spot-check corrections](../../research/transitions/out/spotcheck_gate.json)
- [Split leakage audit](../../research/transitions/out/split_leakage.json)
- [Canonical identity cache](../../research/transitions/out/repo_identity.json)
- [Valid-split baseline](../../research/transitions/out/baseline_valid.json)
- [Context feature cache](../../research/transitions/out/context_v0.2.jsonl)
- [First training run](../../research/transitions/out/train_v0.2.json)
- [crates.io candidates](../../research/transitions/out/cratesio_candidates.jsonl)
- [Public docs contracts](../../research/transitions/out/docs_public_safety.jsonl)
- [Rust-for-Linux sample](../../research/transitions/out/rust_for_linux_hunks.jsonl)
