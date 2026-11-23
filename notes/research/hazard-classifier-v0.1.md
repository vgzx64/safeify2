# Hazard classifier v0.1 — the classification target that works

> **Status:** first hazard-classifier result · 2026-11-23 · 12-class hazard
> taxonomy · rule labels agree with blind humans at 0.79 (κ 0.77) · classifier
> 0.684 accuracy / 0.519 macro-F1 against human valid labels · versus 0.24
> macro-F1 for the mechanism target.

The mechanism target asks what a *fix* did; it depends on the maintainer and is
barely predictable from the warning (classification v0.1). The hazard target
asks what the *site* is: why the unsafe operation is needed. It is a property
of the snippet, and this report shows it is classifiable, with a clear error
profile.

## Taxonomy (12 classes, ordered by specificity)

| class | definition |
|---|---|
| `raw_ownership` | raw parts converted into an owned value: `from_raw_parts`, `Box/Vec/...::from_raw`, `into_raw`, `ManuallyDrop` |
| `manual_capacity` | manual length/capacity over unsafe memory: `set_len`, `with_capacity` + unsafe writes |
| `raw_memory` | raw pointer read/write/copy/swap: `ptr::read/write/copy/swap`, `copy_nonoverlapping` |
| `uninit_memory` | `uninitialized`, `zeroed`, `MaybeUninit`, `assume_init` |
| `reinterpret` | `transmute`, cast to reference, `from_utf8_unchecked`, `from_bytes_with_nul_unchecked` |
| `raw_deref` | dereference/mutation through a raw pointer (`&*p`, `*p = ...`) |
| `unchecked_index` | `get_unchecked`, pointer `add`/`offset`/`sub` |
| `ffi_boundary` | `extern "C"`, `#[no_mangle]`, libc/winapi boundaries |
| `unsafe_trait` | `unsafe impl` / `unsafe trait` |
| `unsafe_contract` | `unsafe fn` whose contract the caller upholds |
| `unsafe_call` | unsafe operation delegated to a call whose contract is not visible |
| `unknown` | neither a hazard nor a call visible |

Implemented in `hazard_taxonomy.py` (rules, specificity order). On the v0.5
corpus (962 rows): only **1.7 %** are `unknown`, but `unsafe_call` is the
largest class (311/745 train rows, 42 %). The ten locally determinable hazards
cover 56 % of train and 78 % of valid rows.

## Are the labels right?

Blind re-annotation of 60 train rows (two annotators, stored labels hidden):

| comparison | κ | raw agreement |
|---|---:|---:|
| annotator A vs B | 0.854 | 0.867 |
| annotator B vs rules | 0.873 | 0.883 |
| annotator A vs rules | 0.782 | 0.800 |

And against 87 freshly annotated valid rows: rules vs human agreement **0.793,
κ 0.765**. The taxonomy is reproducible and the rule labels are a fair
approximation of human judgment, with one systematic gap: annotators recognise
FFI call sites (`PQresultStatus`, libpq, OpenSSL) as `ffi_boundary` where the
rules see only a generic call.

## Classifier

Trained on rule-labelled train rows, char TF-IDF + API (and a features variant
in `baseline_features.py`), scored on the frozen valid split:

| evaluation | train rows | valid rows | accuracy | macro F1 |
|---|---:|---:|---:|---:|
| rule labels, 10 determinable hazards | 418 | 68 | 0.779 | 0.592 |
| rule labels, 12 classes | 745 | 87 | 0.759 | 0.574 |
| **human labels, 10 hazards** | 418 | 79 | **0.684** | **0.519** |
| model vs rule labels, same 79 rows | 418 | 79 | 0.671 | 0.565 |

Grouped CV on the rule-labelled train subset: accuracy 0.658, macro F1 0.612.

Per class against human labels: `manual_capacity` F1 0.91, `raw_ownership` 0.82,
`unsafe_trait` 0.81, `uninit_memory` 0.80, `raw_memory` 0.67, `raw_deref` 0.60,
`reinterpret` 0.33, `ffi_boundary` 0.25. The FFI gap is inherited from the
labels; `unchecked_index` and `unsafe_contract` have no support in the valid
split.

For comparison, the mechanism classifier reaches macro F1 0.237 on the same
valid set. The hazard target is roughly twice as learnable, which is the
expected direction: it describes the input rather than the fix.

## What this means

- The classifier of unsafe usage works at the coarse level: 0.68 accuracy /
  0.52 macro F1 against human labels, with interpretable per-class errors.
- Its weak spots are known and fixable in the data, not the model:
  1. **`ffi_boundary` labels** — the rules cannot see a C call behind a Rust
     wrapper; annotating the train set (or adding FFI-aware features: `libc::`,
     `*sys` crates, C-style identifiers) should recover most of the lost
     recall.
  2. **`unsafe_call` coverage** — 42 % of the corpus delegates its contract to
     a callee. This is a legitimate class (not a failure), but it means the
     snippet cannot classify the operation itself; the enclosing function
     signature would help.
  3. **Small classes** — `unchecked_index`, `unsafe_contract` need more valid
     support before their F1 means anything.
- The target is now consistent with the project scope: a classifier of unsafe
  usage, no generation, no patch ranking.

## Next

1. Annotate ~300 train rows for hazard (the valid 87 are already annotated) and
   retrain; this removes rule-label noise and gives a genuine human-supervised
   classification result.
2. Add FFI-aware features and C-style identifier detection.
3. Feed the hazard class into the mechanism model as an auxiliary input (does
   knowing the hazard improve conditional mechanism top-1?), which is still a
   classification problem.

## Files

```bash
cd safeify-data/transitions
python hazard_taxonomy.py                # taxonomy + self-check
python make_hazard_audit.py              # rule labels + blind sample
python baseline_hazard.py                # out/baseline_hazard_v0.1.{json,md}
python score_hazard_agreement.py         # adjudication/hazard/agreement.json
python make_hazard_valid_batches.py      # blind valid batches
python hazard_human_eval.py              # out/hazard_human_v0.1.{json,md}
```

Artifacts: `hazard_taxonomy.py`, `out/hazard_labels.jsonl` (962 rows),
`adjudication/hazard/` (60-row blind sample + annotator labels + agreement),
`adjudication/hazard_valid/` (87-row human labels for the frozen valid split),
`out/baseline_hazard_v0.1.{json,md}`, `out/hazard_human_v0.1.{json,md}`.
