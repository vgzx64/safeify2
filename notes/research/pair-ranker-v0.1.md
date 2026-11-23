# Pair-level ranker v0.1 — can a model verify a candidate replacement?

> **Scope note (2026-11-23):** this analysis is auxiliary and closed. The
> project deliverable is a **classifier of unsafe usage**, not a repair
> pipeline. The three-layer generator/ranker/compiler architecture discussed
> below is an analysis of what the labels mean, not a build plan; do not turn it
> into the product.

> **Status:** baseline · 2026-11-23 · valid AUC 0.97-0.99 on random and
> same-mechanism hard negatives · but the signal is 6 hand-written numeric
> features; char n-grams alone are worse than chance · natural negatives are
> trivially separable · on near-miss negatives the ranker is at chance (0.611),
> so mechanical verification, not the model, must decide validity.

The suggestion pipeline proposes a candidate fix and then must decide whether it
is valid. That is a pair-classification problem — `(old, candidate_new)` —
and unlike mechanism prediction it receives the fix as an input. This first
baseline asks how much of the task is already solved by shallow compatibility
cues.

## Data and negatives

From `out/mechanism_dataset_v05.jsonl` (962 rows; frozen 22 valid Y / 65 valid
M/N):

| pair kind | construction | train | valid |
|---|---|---:|---:|
| positive | real audited old→new (Y rows) | 318 | 22 |
| natural negative | M/N row's old→new (unsafe stays) | 427 | 65 |
| hard negative | Y old paired with another Y's `new` from a **different repository** | 318 | 22 |

Hard-negative donors for valid come from train repositories only. Two donor
variants: `random` (any other repo) and `mechanism` (same mechanism class, so
the API vocabulary overlaps).

## Features

- char 2-5 TF-IDF over `old ⧺ new` (the v0.1 attempt, TF-IDF only);
- six numeric pair features: does the candidate still contain unsafe, does the
  old snippet, identifier Jaccard, identifier containment, length ratio, and
  whether the candidate uses a common safe marker (`get(`, `try_into`,
  `resize(`, `MaybeUninit`, `Cell`, …).

Model: balanced logistic regression. Fit on train pairs, score valid once.

## Results (valid, n = 22 positives + negatives)

| hard negatives | training mix | CV AUC | valid hard AUC | valid natural AUC |
|---|---|---:|---:|---:|
| random | + natural | 0.933 | 0.990 | 0.971 |
| random | hard only | 0.989 | 0.996 | 0.201 |
| mechanism | + natural | 0.930 | 0.973 | 0.971 |
| mechanism | hard only | 0.984 | 0.996 | 0.208 |

Ablation on the `mechanism` + natural configuration:

| features | valid hard AUC | valid natural AUC |
|---|---:|---:|
| TF-IDF + numeric | 0.973 | 0.971 |
| TF-IDF only | 0.310 | 0.562 |
| numeric only | 0.986 | 0.962 |

Single-feature reference: whether the candidate still contains an unsafe
operation separates natural negatives at AUC 0.962.

## What this actually shows

Three things, in order of importance:

1. **The pair signal is real but shallow.** A candidate from a different crate
   is detected at 0.97-0.99 AUC. The donor stays hard when it comes from the
   same mechanism class, so it is not the mechanism vocabulary that gives it
   away — it is repo-internal identifier overlap and the absence of unsafe code.
2. **Char n-grams add nothing, and alone they mislead.** TF-IDF-only hard AUC
   is 0.31: it latches onto repository style rather than compatibility. All the
   signal is in six numeric features. That is a compatibility heuristic, not a
   semantic verifier, and it should be described as such.
3. **Negatives must be mixed.** A model trained only on hard negatives loses
   the unsafe-presence check entirely (natural AUC 0.20); a model trained with
   natural negatives keeps both. Natural negatives are trivial on their own and
   must never be the only negative family.

### Near-miss test

Same old snippet, the real candidate versus a perturbed twin (36 comparisons,
12 per perturbation; chance 0.5):

| perturbation | real candidate ranked above perturbed |
|---|---:|
| changed numeric index | 1.000 |
| swapped identifier | 0.500 |
| dropped guard/check line | 0.250 |
| **overall** | **0.611** |

Mean score margin is −0.0007: the model is at chance on the only question that
matters for a verifier. Dropping a bounds/guard line — exactly the unsafe-adjacent
mistake a verifier must catch — is *preferred* by the model 75 % of the time.
The `change_index` win is a naturalness artifact of the character model, not
semantic understanding.

## Consequence for the architecture

The suggestion pipeline should therefore use three layers, not one learned
verifier:

1. **rule/pattern generator** — propose a candidate from the mechanism and the
   API (KB);
2. **cheap learned filter** — the numeric compatibility model above plus an
   explicit unsafe-presence check, to drop unrelated candidates;
3. **mechanical verification** — compile, clippy, tests (and Miri where
   feasible) as the only thing allowed to say "this replacement is valid".

A learned semantic verifier would need the near-miss data; until then, the
compiler is the verifier and the model is a ranker.

## Files

```bash
cd safeify-data/transitions
python baseline_pair.py      # out/baseline_pair_v0.1.{json,md}
```

Artifacts: `baseline_pair.py`, `out/baseline_pair_v0.1.json`,
`out/baseline_pair_v0.1.md`. Dataset and splits unchanged.
