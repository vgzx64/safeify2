# LLM adjudication

> Status: pilot labels, not a frozen dataset.

The rubric is [RUBRIC.md](RUBRIC.md). Labels are semantic decisions about the
shown old/new hunk. Compilation, tests, and Miri are intentionally **not**
required: this is a classification/retrieval dataset, not a patch-generation
benchmark.

## Pipeline

```bash
cd /mnt/wd2023/home/dev2/Code/safeify2
python research/transitions/collect_hunks.py      # strict unsafe hunks
python research/transitions/adjudication/make_queue.py --pilot 30 --name pilot_002
# adjudicate via LLM batches -> labels_002a.jsonl / labels_002b.jsonl
python research/transitions/adjudication/merge_labels.py  # edit paths for the batch
```

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

The manual 74-positive set and the 72 CVEfixes LLM `Y` set overlap on 56 rows;
18 are manual-only and 16 are LLM-only. The union is 90 CVEfixes positives
(97 with the 7 RustSec `Y` rows), or 89 distinct (repo, path, function) families.
The manual-only positives were re-adjudicated: 16 kept `Y`, 2 were demoted to `M`.
The reviewed negative core is **123 rows** (58 `N`, 65 `M`, including the 2
reconciliation demotions).

## RustSec

- 1,332 advisories; 863 already in CVEfixes, **469 not**.
- 147 PR/commit URLs fetched as public `.diff`; 189 unsafe-changing hunks:
  39 safe candidates, 61 unsafe-retained, 89 unsafe-added.
- After strict filtering and deduplication, only **12 clean safe candidates**
  remain across 6 repositories. A 12-row adjudication produced 6 `Y`, 2 `M`,
  and 4 `U` (4 vetoes). Issue-URL resolution added 90 same-repo fixes, 59
  hunks, and 4 more clean candidates (not yet adjudicated). RustSec is useful
  for coverage, not a large source of safe replacements.

## Current limits

- Only 206 CVEfixes rows have been adjudicated; the queue has 458.
- crates.io adds 54 adjudicated rows (23 Y / 5 M / 3 N / 23 U).
- Manual spot-checks are not yet a systematic 10–20% sample.
- The negative queue is dominated by `unsafe fn`/`unsafe impl` contract changes;
  these are `M`/`U`, not hard negatives.
- RustSec labels need their own adjudication pass.
