# Mechanism classification baseline (v0.4-plus)

Fit on train (459) and score the frozen valid split (87); test sealed.
Input: `old_snippet` + `api_guess`; positive-task mechanics: predict the
safe-remediation mechanism, or `retain` when unsafe stays (M/N).

## Joint task (mechanism or retain)

| model | valid acc | valid macro-F1 | mechanism suggested on M/N | retain predicted on Y |
|---|---:|---:|---:|---:|
| majority | 0.747 | 0.107 | 0 | 22 |
| api_lookup | 0.655 | 0.137 | 11 | 16 |
| char_lr | 0.598 | 0.203 | 18 | 14 |
| char_api_lr | 0.540 | 0.238 | 26 | 8 |

## Conditional on Y rows (which mechanism)

| model | n | top-1 | top-3 | macro-F1 | 95% CI top-1 |
|---|---:|---:|---:|---:|---:|
| majority | 22 | 0.000 | 0.136 | 0.000 | 0.000-0.000 |
| api_lookup | 22 | 0.136 | 0.136 | 0.095 | 0.000-0.274 |
| char_lr | 22 | 0.227 | 0.773 | 0.321 | 0.045-0.409 |
| char_api_lr | 22 | 0.364 | 0.818 | 0.379 | 0.182-0.591 |
| conditional_char_lr (train Y only: 185) | 22 | 0.636 | 0.864 | 0.438 | - |

Constant baselines over the same valid Y rows:

- majority mechanism (safe_wrapper, restructure, checked_api): top-1 0.455, top-3 0.500
- majority family (ownership, safe_api, checked): top-1 0.136, top-3 0.636

Family view of the conditional model (5 families + retain):

| model | top-1 | top-3 | macro-F1 |
|---|---:|---:|---:|
| conditional_char_lr | 0.636 | 0.909 | 0.407 |

Valid Y mechanism support:

- safe_wrapper: 10
- capacity_ops: 3
- init_memory: 3
- unnecessary: 2
- interior_mutability: 2
- restructure: 1
- slice_view: 1
