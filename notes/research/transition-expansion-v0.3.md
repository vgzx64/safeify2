# Transition expansion and audit — v0.3

> **Status:** draft · 2026-11-22 · 676 rows (459 train / 87 valid / 130 test) ·
> 469 new rows adjudicated · frozen valid/test unchanged · verdict: expansion
> in this range does **not** move held-out quality; no GPU fine-tune.

Follows the v0.2 baseline suite ([`safeify-data/transitions/README.md`](../../safeify-data/transitions/README.md#baseline-suite-2026-11-21)).
The question was whether more labelled rows lift the transfer ceiling (valid
AUC 0.64) before spending GPU time on a fine-tune.

## 1. Expansion pool

Three extractors and the crates.io miner had already written candidate rows
that v0.2 never adjudicated. `build_expansion.py` collected them:

| source file | untouched rows |
|---|---:|
| `out/all_hunks.jsonl` (CVEfixes) | 405 |
| `out/cratesio_candidates.jsonl` | 678 |
| `out/rustsec_hunks.jsonl` + issue hunks + Linux | 205 |
| **raw pool** | **1,288** |

Rows were deduplicated against the frozen core and against each other by
whitespace-normalised `old_snippet` (prefer CVEfixes > RustSec > crates.io),
leaving **835 distinct rows**. Each row inherited the frozen split of its
canonical repository (`repo_identity.py`); rows from repositories not in any
split stayed `unassigned`:

| split | rows |
|---|---:|
| train repositories | 458 |
| frozen valid repositories | 129 |
| sealed test repositories | 199 |
| unassigned (new repositories) | 49 |

Only train and unassigned rows enter the audit: valid/test rows would either
break the frozen comparison or stay sealed.

## 2. Audit

`make_expansion_queue.py` dropped undecidable rows (empty old or new snippet)
and wrote ten batches of up to 48 rows (469 total) with clipped snippets.
Each batch was adjudicated independently under
[`adjudication/RUBRIC.md`](../../safeify-data/transitions/adjudication/RUBRIC.md)
and merged by `merge_expansion_labels.py`, which rejects missing/extra ids,
illegal enums, a Y whose new snippet still contains an unsafe operation, an M
without quoted evidence, and a U without a veto reason.

| label | rows |
|---|---:|
| Y (safe replacement) | 30 |
| M (guard/restructure) | 26 |
| N (unsafe retained) | 335 |
| U (unrelated) | 78 |
| **total** | **469** |

By heuristic kind (the audit's own yield):

| kind | rows | Y | M | N | U |
|---|---:|---:|---:|---:|---:|
| `safe_candidate` | 52 | 30 | 1 | 8 | 13 |
| `unsafe_retained` | 265 | 0 | 18 | 239 | 8 |
| `unsafe_added` | 152 | 0 | 7 | 88 | 57 |

Two things matter here. First, the heuristic "unsafe disappeared" is right
about 58 % of the time — close to the 77 % manual rate of the v0.2 `safe`
pool and not good enough to label without review. Second, `unsafe_added`
hunks are mostly `U` (57/152): the fix touched `unsafe` code in another
function, not the warning. They are not usable negatives.

## 3. v0.3 build

`build_v03.py` keeps the frozen v0.2 rows untouched, drops `U`, maps
Y→1 / M,N→0, and places every audited row whose repository is not in
valid/test into `train`. Negatives are capped at 20 per repository
(`ponytail:` flat cap — arrayfire alone had 121 and flatbuffers 65, so an
uncapped pool would be one advisory repeated). New repositories join `train`;
valid/test stay frozen, so the comparison against v0.2 is like for like.

| | v0.2 | v0.3 |
|---|---:|---:|
| rows | 433 | 676 |
| train | 216 (54 Y) | 459 (84 Y) |
| valid | 87 (22 Y) | 87 (22 Y) |
| test sealed | 130 | 130 |
| repositories | 154 | 173 |
| cross-split duplicate snippets | 0 | 0 |

Dropped from the audited pool: 78 `U`, 148 over the per-repository cap.

## 4. Results

Same protocol: repository-grouped 5-fold CV on train, fit on train, score the
frozen 87-row valid set, test sealed, `old_snippet` only.

| model | CV AUC v0.2 → v0.3 | valid AUC v0.2 → v0.3 | valid F1(Y) | valid AP |
|---|---:|---:|---:|---:|
| majority | .500 → .500 | .500 → .500 | .000 | .253 |
| word TF-IDF + LR | .716 → .715 | .544 → .569 | .412 | .347 |
| char TF-IDF + LR | .868 → .762 | **.641 → .624** | **.444** | .392 |
| TF-IDF union + LR | .833 → .783 | .579 → .598 | .353 | .361 |
| TF-IDF+SVD + GB | .582 → .608 | .601 → .497 | .286 | .357 |
| TF-IDF+SVD + RF | .563 → .698 | .559 → .564 | .148 | .326 |

95 % bootstrap intervals on valid still overlap chance for every model: char
TF-IDF AUC 0.483-0.761 (v0.3), AP 0.237-0.613.

The one visible change is the operating point, not the ranking: at threshold
0.5 char TF-IDF now flags 14/87 rows with precision 0.571 and recall 0.364
(was 15 rows, 0.467, 0.318). Ranking quality (AUC, AP) is flat.

**The decisive number is the precision ceiling.** Sweeping the threshold over
the valid scores, the highest precision reachable by any operating point is
0.571 (v0.2) and 0.625 (v0.3) — precision 0.7 is *unreachable*, let alone
0.8-0.9. There is no high-precision region to calibrate an abstaining tool
against.

Grouped CV fell from .868 to .762 because 305 of the 459 train rows are
harder, cross-source negatives; the train/valid gap narrowed from .23 to .14
rows-of-AUC. Neither movement is a quality gain.

## 5. Verdict

Adding 243 audited rows (30 positives) did not raise held-out ranking
quality. The bottleneck is not row count in the 0.4-0.7k range: the frozen
valid set is scored on 31 unseen repositories and the snippet-only
representation tops out near AUC 0.62 with no high-precision operating point.
Fine-tuning ModernBERT on the current labels would buy noise, not signal.

Cheapest next levers, in order:

1. **More positives from the same recipe**, not more negatives. crates.io
   version pairs are the only source with safe candidates in bulk (~16 % of
   mined `cratesio` rows); mine more advisories and audit those. If AUC does
   not move with 2-3× positives, the representation is the wall.
2. **Label quality on positives.** A Y must show a concrete safe replacement;
   42 % of audited `safe_candidate` rows were U/N/M. Better candidate text
   (full function + fixed lines) would raise the Y base rate before review.
3. **Pivot the modelling line** to pair classification, where the fixed code
   is an input rather than a label, and the frozen core is external
   validation. The current task asks the model to predict the fix from the
   pre-fix snippet alone.

Not worth doing yet: a GPU fine-tune, more transformer probes, or a second
bias/variance study on 87 valid rows.

## 6. Commands and files

```bash
cd safeify-data/transitions
python build_expansion.py           # out/expansion_pool_draft.jsonl
python make_expansion_queue.py      # adjudication/expansion/batch_*.jsonl
# ... adjudication under adjudication/RUBRIC.md ...
python merge_expansion_labels.py --write   # adjudication/expansion/labeled.jsonl
python build_v03.py                 # out/transitions_core_v0.3_draft.jsonl
python baseline_suite.py --version v0.3    # out/baseline_suite_v0.3.{json,md}
```

New artifacts: `out/expansion_pool_draft.jsonl`,
`out/expansion_pool_stats.json`, `adjudication/expansion/` (queue, batches,
labels, merged + stats), `out/transitions_core_v0.3_draft.jsonl`,
`out/transitions_core_v0.3_stats.json`, `out/baseline_suite_v0.3.{json,md}`.
v0.2 and its baseline outputs are unchanged (the suite reproduces v0.2 byte
for byte).
