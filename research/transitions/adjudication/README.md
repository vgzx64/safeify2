# LLM adjudication

> Status: v0.2 **frozen** (2026-11-08); 8 dataset gates pass; split leakage 0; labels verified by two blind spot-checks plus a focused M/N re-label.

The rubric is [RUBRIC.md](RUBRIC.md). Labels are semantic decisions about the
shown old/new hunk. Compilation, tests, and Miri are intentionally **not**
required: this is a classification/retrieval dataset, not a patch-generation
benchmark.

## Pipeline

```bash
cd /mnt/wd2023/home/dev2/Code/safeify2
python research/transitions/collect_hunks.py                  # strict unsafe hunks
python research/transitions/adjudication/build_batches.py     # 161 queue + 170 expansion rows
# adjudicate gate_aNN / gate_bNN chunks via LLM -> labels_gate_*.jsonl
python research/transitions/adjudication/validate_gate_labels.py
python research/transitions/adjudication/merge_gate_batches.py --strict
python research/transitions/adjudication/spotcheck_gate.py    # documented corrections
python research/transitions/adjudication/make_spotcheck3.py   # blind M/N sample
python research/transitions/score_spotcheck.py ...            # agree/kappa report
python research/transitions/label_reliability.py              # combined across passes
python research/transitions/rebuild_v01.py                    # core + splits + gates
python research/transitions/freeze_v02.py                     # gates + freeze + sha256
```

`make_queue.py` / `merge_labels.py` are the older round-12 helpers; the gate
run uses the batch scripts above.

## What the pilot showed

The first queue used `api_guess`, whose generic `ptr::deref`/`as_ref` patterns
match safe code. In the first 60-row pilot, **31/60 rows were vetoed** as
unrelated or not actually unsafe. That queue was not usable.

`collect_hunks.py` now uses a strict signal: the `unsafe` keyword, or a known
unsafe API (`ptr::read`, `get_unchecked`, `set_len`, `assume_init`, `transmute`,
`from_raw*`, etc.). That reduced CVEfixes from 1,567 raw hunks to **772** strict
hunks: 121 safe candidates, 366 unsafe-retained, 285 unsafe-added.

The CVEfixes adjudications (`pilot_002` + `pilot_003` + `pilot_004a/b` +
`pilot_005/006`) produced:

| Label | Count |
|---|---:|
| `Y` replaceable | 73 |
| `M` conditional/guard | 57 |
| `N` keep | 55 |
| `U` unresolved | 21 |
| vetoed | 19 |

A human spot-check of five Y rows found one clipped-context overclaim
(`crossbeam-epoch` `mem::uninitialized` → `MaybeUninit::uninit`, with later
unsafe writes not shown); it was corrected from `Y` to `M`. The LLM labels are
useful but not self-validating.

The manual 74-positive set and the CVEfixes LLM `Y` set overlap on 56 rows; 18
are manual-only and 16 are LLM-only. The manual-only positives were
re-adjudicated: 16 kept `Y`, 2 were demoted to `M`.

## Gate-closing run (2026-11-07)

The round-12 state (276 reviewed; 206/458 queue; 81 negative families) failed
the negative and queue gates. A scoped run closed them:

- **Batch A** — 161 unreviewed CVEfixes queue rows, one per family across all
  118 remaining families, then second rows to reach the coverage target.
- **Batch B** — 170 untouched crates.io/RustSec retained families, one row per
  family.
- **11 LLM batches** of 27–29 rows; every batch validated for exact id sets,
  enum values, and evidence quotes (`validate_gate_labels.py`).

Result: **331 new adjudications**, 302 with a usable `N`/`M` label, 1 `Y`, and 28
vetoes. One of the two new `Y` claims was demoted on spot-check: the
RUSTSEC-2021-0144 pointer cast keeps `T: ?Sized`, so the safe cast needs a
`Sized` bound and the row is `M`, not `Y`. The correction is recorded in
`out/spotcheck_gate.json` and applied by `spotcheck_gate.py`.

Known batch artefacts: several `unsafe` calls appear without the keyword
because the enclosing `unsafe {` line is outside the clipped snippet; the
prompts treat `from_raw_parts`, `ptr::copy`, `set_len`, `uninitialized`, etc. as
unsafe operations and do not veto them on the missing keyword.

## Current state

| Metric | Value |
|---|---:|
| Reviewed rows | 607 |
| CVEfixes / crates.io / RustSec / Linux | 367 / 194 / 45 / 1 |
| `Y` / `M` / `N` / `U` | 104 / 166 / 259 / 78 |
| Vetoed | 76 |
| Positive union | 120 rows / 110 families |
| Negative core | 425 rows / 325 families |
| Queue coverage | 367/458 (80.1%) |

The frozen v0.2 core is 433 rows (109 `Y`, 193 `N`, 131 `M`), split 216 train /
87 valid / 130 test on canonical repository keys. Eight gates pass in
`out/transitions_core_v0.2_quality.json`; `check_split_leakage.py` reports 0
cross-split leakage.

## RustSec

- 1,332 advisories; 863 already in CVEfixes, **469 not**.
- 147 PR/commit URLs fetched as public `.diff`; 189 unsafe-changing hunks:
  39 safe candidates, 61 unsafe-retained, 89 unsafe-added.
- After strict filtering and deduplication, only **12 clean safe candidates**
  remain across 6 repositories. A 12-row adjudication produced 6 `Y`, 2 `M`,
  and 4 `U` (4 vetoes). Issue-URL resolution added 90 same-repo fixes, 59
  hunks, and 4 more clean candidates. RustSec is useful for coverage, not a
  large source of safe replacements.
- The gate run added 45 RustSec rows total; most are `N`/`M`, as expected.

## Current limits

- Queue coverage just clears the gate at 80.1%; 91 CVEfixes queue rows remain.
- crates.io contributes 194 reviewed rows but only 23 new `Y`; its value is
  negative/guard coverage.
- Spot-checks are not a random 10–20% sample of the whole pool: 36 + 24 blind
  rows, with the second sample deliberately focused on M/N. Five corrections
  are the current record.
- **M vs N is not a reproducible label.** Two annotators agree on Y-vs-not-Y
  (0.95, kappa 0.82 over 83 rows) but on M-vs-N only kappa 0.42-0.52. Rules 9
  and 10 of the rubric pin the boundary down, but the residual disagreements
  flip both ways; the frozen dataset therefore trains the binary target and
  keeps `M` as a descriptor.
- Negatives are concentrated: google/flatbuffers is 57 of 324 negative rows.
- The negative queue is dominated by `unsafe fn`/`unsafe impl` contract changes;
  these are `M`/`U`, not hard negatives.
- Three corrections from the verification passes live in `corrections.jsonl` and
  are replayed by every rebuild.
- The earlier repo-alias split leakage is fixed: `repo_identity.py` keys splits
  on `host/owner/repo` and the audit now reports 0 cross-split duplicates.
