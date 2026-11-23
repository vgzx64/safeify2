# Mechanism model v0.1 — predicting the safe-remediation mechanism

> **Status:** first result · 2026-11-23 · 139 Y rows labelled (71 newly audited) ·
> 84 train / 22 valid Y rows · top-1 0.455 (95 % CI 0.227-0.636) · top-3 0.864 ·
> not deployable; the label budget is the limit, not the idea.

Follows the negative binary result ([transition-expansion-v0.3.md](transition-expansion-v0.3.md)).
The binary target asked "did the maintainer replace it?" and capped at AUC 0.62
with no precision above 0.625. This line changes the target: **what safe
mechanism does the fix use, or does unsafe stay?** A mechanism is visible in the
fix diff, so the label is observable rather than a judgement about the
maintainer, and it is what a suggestion tool would actually emit.

## 1. Taxonomy

Defined in [`mechanism_taxonomy.py`](../../safeify-data/transitions/mechanism_taxonomy.py).
Ten fine classes in five families, plus `retain` as the abstention class (M/N
rows: unsafe stays, so suggesting a mechanism would be wrong).

| family | mechanisms |
|---|---|
| checked | `checked_api`, `slice_view` |
| memory | `init_memory`, `capacity_ops` |
| safe_api | `safe_wrapper` |
| ownership | `interior_mutability`, `pin_api`, `restructure` |
| remove | `unnecessary`, `other` |

`retain` covers M and N. The family level exists because some fine classes are
too rare to estimate (e.g. `slice_view` has 1 train row).

## 2. Labels

The audited v0.2/v0.3 corpus has 139 Y rows. 68 already carried a free-text
mechanism in `labels_safe.csv` (mapped mechanically to the taxonomy); the
remaining 71 were labelled in two batches under the same rubric discipline
(`make_mechanism_queue.py` → adjudication → `merge_mechanism_labels.py`, which
rejects unknown mechanisms, family mismatches, missing evidence or bad ids).
53 of the 71 labels are high confidence, 18 medium.

The resulting distribution is the first finding:

| mechanism | train | valid | test (sealed) |
|---|---:|---:|---:|
| retain (M/N) | 375 | 65 | 97 |
| safe_wrapper | 17 | 10 | 4 |
| checked_api | 20 | 0 | 3 |
| init_memory | 16 | 3 | 4 |
| restructure | 13 | 1 | 1 |
| capacity_ops | 7 | 3 | 1 |
| unnecessary | 7 | 2 | 6 |
| interior_mutability | 3 | 2 | 6 |
| pin_api | 0 | 0 | 4 |
| slice_view | 1 | 1 | 2 |
| other | 0 | 0 | 2 |
| **Y total** | **84** | **22** | **33** |

Train and valid disagree sharply about *which* mechanisms occur: `checked_api`
is the largest train class (20) and absent from valid; `safe_wrapper` is the
largest valid class (10). Mechanism mix is repository-specific, which is one
more reason the frozen valid set is a hard test.

## 3. Protocol

`baseline_mechanism.py`: fit on train (459 rows), score the frozen valid split
(87 rows), test sealed. Input is `old_snippet` plus `api_guess`; the fix is
never an input. Two questions are reported:

- **joint** — choose one of 10 mechanisms or `retain`;
- **conditional** — on Y rows only, which mechanism (the suggestion-quality
  question), with a `conditional_char_lr` model trained on the 84 train Y rows
  alone and constant baselines for comparison.

## 4. Results

Joint task on valid (n = 87):

| model | accuracy | macro-F1 | mechanism on M/N rows | retain on Y rows |
|---|---:|---:|---:|---:|
| majority (retain) | 0.747 | 0.107 | 0 | 22 |
| api→mechanism lookup | 0.655 | 0.137 | 11 | 16 |
| char TF-IDF + LR | 0.747 | 0.200 | 4 | 15 |
| char TF-IDF + api + LR | 0.667 | 0.242 | 12 | 14 |

Accuracy is dominated by `retain`; macro-F1 is the number that matters, and it
is low for every model. In particular, no model both abstains on M/N and
suggests a mechanism on Y: the best macro-F1 model emits 12 false suggestions,
the best-abstaining one misses 15 of 22 Y rows.

Conditional task on the 22 valid Y rows:

| model | top-1 | top-3 | macro-F1 |
|---|---:|---:|---:|
| constant top-3 from train | 0.000 | 0.591 | - |
| constant family top-3 | 0.273 | 0.773 | - |
| conditional_char_lr (train on 84 Y) | **0.455** | **0.864** | 0.338 |
| conditional family view | 0.409 | 0.818 | - |

Top-1 is 10/22 (95 % CI 0.227-0.636) — equal to the dominant-class rate of the
valid set, but reached with a diverse predicted distribution
(`init_memory` 5, `safe_wrapper` 5, `interior_mutability` 5, `unnecessary` 3,
`capacity_ops` 2, `slice_view` 1, `checked_api` 1), not by predicting one class.
Top-3 (0.864) is clearly above the constant top-3 list (0.591), so the ranking
carries real information. Family top-1 (0.409) also beats the constant family
baseline (0.273).

## 5. Verdict

The reframed target is **partially learnable but not useful yet**: at 84
training Y rows, top-1 cannot be distinguished from guessing the dominant
mechanism, and 22 valid rows give a ±0.2 interval. Top-3 above the constant
baseline is the encouraging part; a suggestion UI with three ranked candidates
and a human in the loop is the realistic shape.

The correct next step is scale, not architecture: label thousands of mechanism
examples from crate version history (objective old→new pairs, no maintainer
judgement) and validate on these 84/22 real rows. A rule-based mechanism
labeller can produce those weak labels, and its agreement with the 139 audited
mechanisms is measurable first.

## 6. Files and commands

```bash
cd safeify-data/transitions
python mechanism_taxonomy.py        # taxonomy + free-text mapping (no-op, imported)
python make_mechanism_queue.py      # adjudication/mechanisms/batch_*.jsonl
# ... mechanism labels adjudicated ...
python merge_mechanism_labels.py --write   # adjudication/mechanisms/labeled.jsonl
python build_mechanism_dataset.py   # out/mechanism_dataset.jsonl
python baseline_mechanism.py        # out/baseline_mechanism_v0.3.{json,md}
```

Artifacts: `mechanism_taxonomy.py`, `out/mechanism_dataset.jsonl` +
`out/mechanism_dataset_stats.json`, `adjudication/mechanisms/`,
`out/baseline_mechanism_v0.3.{json,md}`. The v0.2/v0.3 cores and the binary
baseline outputs are unchanged.
