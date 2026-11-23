# Pair-level ranker baseline (v0.1)

Given `(old_snippet, candidate_new)`, rank whether the candidate is a
valid safe replacement. Valid rows are scored once; test is sealed.

Two hard-negative constructions: `random` donors from other repositories,
and `mechanism` donors from the same mechanism class (harder, because the
API vocabulary overlaps).

| hard negatives | training mix | CV AUC | valid hard-negative AUC | valid natural-negative AUC |
|---|---|---:|---:|---:|
| random/with_natural | 0.933 | 0.990 | 0.971 |
| random/hard_only | 0.989 | 0.996 | 0.201 |
| mechanism/with_natural | 0.930 | 0.973 | 0.971 |
| mechanism/hard_only | 0.984 | 0.996 | 0.208 |

Near-miss test (same old snippet; real candidate vs perturbed candidate):

real candidate ranked above its perturbed twin in 0.611 of 36 comparisons (chance 0.5), mean margin -0.001

| perturbation | win rate |
|---|---:|
| change_index | 1.000 |
| drop_guard | 0.250 |
| swap_ident | 0.500 |

Ablation (mechanism hard negatives, with natural negatives):

| features | valid hard AUC | valid natural AUC |
|---|---:|---:|
| full | 0.973 | 0.971 |
| tfidf_only | 0.310 | 0.562 |
| numeric_only | 0.986 | 0.962 |

Trivial single-feature baseline (is `unsafe` present in the candidate?): natural-negative AUC 0.962.

Valid hard negatives pair a valid Y row's old snippet with a train Y row's
candidate from a different repository: safe code, wrong replacement.

Pair counts:

| split | positives | natural negatives | hard negatives |
|---|---:|---:|---:|
| train | 318 | 427 | 318 |
| valid | 22 | 65 | 22 |
