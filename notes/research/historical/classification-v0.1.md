# Unsafe-usage classification v0.1 — labels are reliable, the target is the problem

> **Status:** classification baseline · 2026-11-23 · binary AUC 0.655
> (95 % CI 0.529-0.779) · family macro-F1 0.322 · mechanism macro-F1 0.237 ·
> blind annotators reproduce the labels (binary κ 0.96, mechanism κ 0.80), so
> the weakness is not label noise — it is that the labels describe the *fix*
> while the model sees only the *warning*.

The deliverable is a classifier, not a generator: assign an unsafe site to a
remediation class (`retain` when none applies), or at the coarser levels to a
family, or to the binary "is a safe remediation available at all". This report
scores those three levels on the frozen valid split and measures whether the
labels themselves are reproducible.

## Formulation

- input: `old_snippet` (+ `api_guess`);
- targets, from cheap to fine:
  - **binary** — `retain` vs any mechanism;
  - **family** — retain + 5 families (checked, memory, safe_api, ownership, remove);
  - **mechanism** — 11 classes (retain + 10 mechanisms).
- protocol: fit on train (745 rows), score the frozen 87-row valid set once,
  test sealed; group-aware only in CV.

## Results on valid

| model | binary AUC | binary acc | family acc | family macro-F1 | mechanism acc | mechanism macro-F1 |
|---|---:|---:|---:|---:|---:|---:|
| majority (retain) | - | 0.747 | 0.747 | 0.244 | 0.747 | 0.078 |
| api lookup | - | 0.644 | 0.644 | 0.304 | 0.609 | 0.101 |
| char TF-IDF + LR | - | 0.471 | 0.414 | 0.269 | 0.391 | 0.138 |
| char TF-IDF + api + LR | - | 0.425 | 0.368 | 0.310 | 0.368 | 0.237 |
| hierarchical (family→mechanism) | - | 0.483 | 0.425 | 0.322 | 0.425 | 0.237 |
| fingerprint features + GB | **0.655** | 0.632 | - | - | 0.563 | 0.126 |
| fingerprint features + LR | 0.557 | 0.586 | - | - | 0.172 | 0.107 |
| features + text + api + LR | 0.565 | 0.540 | - | - | 0.345 | 0.205 |

Bootstrap 95 % CI on the best binary model (features + GB): AUC 0.529-0.779,
accuracy 0.55-0.71. Grouped CV on train is more optimistic (AUC 0.70), the same
CV-to-valid drop as everywhere else in this track.

Per-class family view (char+api LR): retain F1 0.419 (support 65), memory 0.571
(6), safe_api 0.286 (10), ownership 0.250 (3), remove 0.222 (2), checked 0.000
(1). Mechanism level is similar: most classes are predicted rarely or never.

## Label reliability (blind re-annotation)

60 train rows (40 stored-Y, 20 stored-retain) were re-annotated independently by
two annotators that saw only the snippets, not the stored label:

| comparison | κ | raw agreement |
|---|---:|---:|
| binary Y-vs-not, annotator A vs B | 0.963 | 0.983 |
| binary, A vs stored | 1.000 | 1.000 |
| binary, B vs stored | 0.963 | 0.983 |
| mechanism, A vs B (39 both-Y rows) | 0.795 | 0.821 |
| mechanism, A vs stored | 0.822 | - |
| mechanism, B vs stored | 0.852 | - |

So the labels are **reproducible**. The earlier M/N instability (κ 0.42-0.52)
does not extend to the binary Y-vs-not decision or to the mechanism class.

## Diagnosis

If the labels are reliable and the classifier is weak, the problem is what the
model is asked to infer. Both annotators — and the original labellers — had the
fixed code in front of them when assigning the mechanism. The model has only the
pre-fix snippet. "Which safe mechanism was used" depends on the maintainer's
choice (guard vs replacement vs rewrite) and on the fix, not on the warning
alone. That is an information gap, not (only) a modelling gap.

Evidence in one line: feature+GB reaches AUC 0.655 with reliable labels; a
model that saw the fix would classify the mechanism almost trivially (that is
the pair-ranker setting, where AUC was 0.97 — but there the answer is nearly the
input).

## Recommendation: classify the hazard, not the fix

The version of "classify unsafe usage" that is well-posed from the snippet:

| hazard category | what it looks like |
|---|---|
| ffi_boundary | `extern "C"` calls, `#[no_mangle]`, raw handles |
| unchecked_index | `get_unchecked`, pointer offsets, `*ptr.add` |
| uninit_memory | `uninitialized`, `zeroed`, `MaybeUninit`/`assume_init` |
| manual_capacity | `set_len`, `with_capacity` + write, reserve tricks |
| raw_ownership | `from_raw_parts`, `from_raw`, `into_raw`, `ManuallyDrop` |
| reinterpret | `transmute`, pointer casts to references |
| unsafe_trait | `unsafe impl`, `unsafe trait` |
| unsafe_contract | `unsafe fn` whose contract the caller must uphold |

These are properties of the snippet, derivable by inspection, and they are what
a triage tool needs: they decide whether a checked alternative plausibly exists.
The mechanism then becomes a conditional second stage (`hazard → mechanism`)
trained only where a fix is visible and audited, which is exactly the data the
mechanism model already has (318 train Y, conditional top-1 0.59, top-3 0.86).

This keeps the deliverable a classifier and drops the generator/verifier framing
entirely. The next round should (a) define the hazard taxonomy with rule
extraction, (b) audit a sample for label agreement, (c) train the hazard
classifier on the same frozen splits.

## Files

```bash
cd safeify-data/transitions
python baseline_classification.py     # out/baseline_classification_v0.5.{json,md}
python features_unsafe.py             # feature extractor self-check
python baseline_features.py           # out/baseline_features_v0.5.{json,md}
python make_agreement_sample.py       # adjudication/agreement/sample.jsonl
python score_agreement.py             # adjudication/agreement/agreement.json
```

Artifacts: the four scripts and their outputs; the blind sample and the two
annotator label files under `adjudication/agreement/`. Dataset and splits are
unchanged; test stays sealed.
