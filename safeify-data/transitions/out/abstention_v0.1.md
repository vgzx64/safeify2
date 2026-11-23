# Abstention stage (v0.5 mechanism data)

Requirement: suggested mechanisms should be right at least 80% of the time;
silence is cheap, a wrong suggestion is not. Policies tuned on grouped
out-of-fold train predictions, scored once on the frozen 87-row valid split.

## one_stage_balanced

argmax (no abstention): flagged 66/87, suggestion precision 0.288, mechanism top-1 among flagged 0.212
tuned margin (+0.55): flagged 11/87, precision 0.545 (0.250-0.857), recall 0.273, mechanism top-1 0.545

## one_stage_unbalanced

argmax (no abstention): flagged 12/87, suggestion precision 0.500, mechanism top-1 among flagged 0.333
tuned margin (+0.45): flagged 2/87, precision 0.000 (0.000-0.000), recall 0.000, mechanism top-1 0.000

## two_stage

gate threshold 0.90: flagged 0/87, precision n/a (n/a), recall 0.000, mechanism top-1 n/a

## Valid risk-coverage curve (one-stage, balanced)

| margin | flagged | suggestion precision | recall |
|---:|---:|---:|---:|
| -0.95 | 87 | 0.253 | 1.000 |
| -0.85 | 87 | 0.253 | 1.000 |
| -0.75 | 87 | 0.253 | 1.000 |
| -0.65 | 87 | 0.253 | 1.000 |
| -0.55 | 87 | 0.253 | 1.000 |
| -0.45 | 87 | 0.253 | 1.000 |
| -0.35 | 87 | 0.253 | 1.000 |
| -0.25 | 86 | 0.256 | 1.000 |
| -0.15 | 86 | 0.256 | 1.000 |
| -0.05 | 78 | 0.256 | 0.909 |
| +0.05 | 40 | 0.350 | 0.636 |
| +0.15 | 21 | 0.381 | 0.364 |
| +0.25 | 15 | 0.400 | 0.273 |
| +0.35 | 15 | 0.400 | 0.273 |
| +0.45 | 15 | 0.400 | 0.273 |
| +0.55 | 11 | 0.545 | 0.273 |
| +0.65 | 8 | 0.500 | 0.182 |
| +0.75 | 4 | 0.500 | 0.091 |
| +0.85 | 2 | 0.000 | 0.000 |

Best suggestion precision reachable on valid: 0.545 (target 80%).
