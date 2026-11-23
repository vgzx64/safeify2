# Abstention stage v0.1 — can the mechanism model be made safe to deploy?

> **Status:** negative result · 2026-11-23 · policies tuned on grouped
> out-of-fold train predictions, scored once on the frozen 87-row valid split ·
> best reachable suggestion precision 0.545 (n=11), target 0.80 · calibration
> cannot create signal; the pair ranker is the next step.

The mechanism model (v0.5 data, train Y 318) suggests a mechanism for 47 of 65
M/N valid rows when it answers with its argmax. A developer tool needs the
opposite asymmetry: silence is cheap, a wrong "use this API" is not. This round
asks whether an abstention policy over the existing scores can meet a
precision-first requirement.

## Protocol

- Data: `out/mechanism_dataset_v05.jsonl` (962 rows; 745 train / 87 valid /
  130 sealed test).
- Features: char TF-IDF over `old_snippet` + one-hot `api_guess`, as in the
  mechanism baselines.
- The abstention policy is selected on grouped 5-fold out-of-fold predictions
  on **train** (repo-grouped), then applied once to **valid**. Test untouched.
- Requirement: suggested mechanisms should be right ≥ 80 % of the time.

Policies compared:

| policy | decision rule |
|---|---|
| one-stage argmax, balanced | answer with argmax class; "flagged" = argmax ≠ retain |
| one-stage argmax, unbalanced | same, plain logistic regression (conservative) |
| one-stage margin, balanced | suggest only if max P(mechanism) − P(retain) ≥ m |
| two-stage gate | binary replaceability gate, then the conditional mechanism model |

## Results on valid (n = 87; 22 Y, 65 M/N)

| policy | flagged | suggestion precision | recall of Y | mechanism top-1 among flagged |
|---|---:|---:|---:|---:|
| one-stage argmax, balanced | 66 | 0.288 | 0.864 | 0.212 |
| one-stage margin, balanced (m = +0.55) | 11 | **0.545** (0.250-0.857) | 0.273 | **0.545** |
| one-stage argmax, unbalanced | 12 | 0.500 | 0.273 | 0.333 |
| one-stage margin, unbalanced (m = +0.45) | 2 | 0.000 | 0.000 | 0.000 |
| two-stage gate (t = 0.90) | 0 | n/a | 0.000 | n/a |

The balanced margin policy is chosen on train CV, where it reaches precision
0.806 at 36/745 flagged (4.8 % coverage). On valid the same threshold flags
11 rows at 0.545. The 95 % interval on that precision is 0.25-0.86, and the
best precision at *any* margin on the valid risk-coverage curve is 0.545.

Valid risk-coverage curve (one-stage, balanced):

| margin | flagged | precision | recall |
|---:|---:|---:|---:|
| −0.05 | 78 | 0.256 | 0.909 |
| +0.05 | 40 | 0.350 | 0.636 |
| +0.15 | 21 | 0.381 | 0.364 |
| +0.25 | 15 | 0.400 | 0.273 |
| +0.55 | 11 | 0.545 | 0.273 |
| +0.65 | 8 | 0.500 | 0.182 |

## Verdict

Abstention does not rescue the snippet-only joint model. The score that would
have to be thresholded has a low precision ceiling to begin with (AUC ≈ 0.62 on
this split), and a policy that looks acceptable on CV does not transfer to
unseen repositories: 0.806 on CV, 0.545 on valid. The two-stage variant is
worse still — the binary gate's CV threshold flags nothing on valid, because the
gate's probability distribution shifts across repositories.

This closes the "deployable suggestion from the pre-fix snippet alone" question
in the same way as the binary result: the information is not there. What remains
is to give the model the candidate fix as an input.

## Next: pair-level ranker

Formulation: score `(old_snippet, candidate_new)` → is this a valid safe
replacement? The candidate arrives from the mechanism/KB generator, so the
verifier only has to rank, not invent. Labels are objective and free:

- positives — real audited old→new pairs (373 Y rows across the three sources);
- natural negatives — M/N rows where the new snippet keeps unsafe code (this
  measures the trivial "unsafe still present" shortcut);
- hard negatives — a Y old paired with another Y's new snippet from a different
  repository, i.e. unsafe-free but semantically wrong (this is the signal a
  ranker must actually have).

Report AUC and precision@k on both negative families separately and score the
frozen valid split once. If the hard-negative AUC is near chance, the suggestion
pipeline needs a different verifier (compiler/tests), not a bigger encoder.

## Files

```bash
cd safeify-data/transitions
python baseline_abstention.py       # out/abstention_v0.1.{json,md}
```

Artifacts: `baseline_abstention.py`, `out/abstention_v0.1.json`,
`out/abstention_v0.1.md`. Dataset, splits and previous results unchanged.
