# Mechanism classification baseline (v0.3)

Fit on train (459) and score the frozen valid split (87); test sealed.
Input: `old_snippet` + `api_guess`; positive-task mechanics: predict the
safe-remediation mechanism, or `retain` when unsafe stays (M/N).

## Joint task (mechanism or retain)

| model | valid acc | valid macro-F1 | mechanism suggested on M/N | retain predicted on Y |
|---|---:|---:|---:|---:|
| majority | 0.747 | 0.107 | 0 | 22 |
| api_lookup | 0.655 | 0.137 | 11 | 16 |
| char_lr | 0.747 | 0.200 | 4 | 15 |
| char_api_lr | 0.667 | 0.242 | 12 | 14 |

## Conditional on Y rows (which mechanism)

| model | n | top-1 | top-3 | macro-F1 | 95% CI top-1 |
|---|---:|---:|---:|---:|---:|
| majority | 22 | 0.000 | 0.136 | 0.000 | 0.000-0.000 |
| api_lookup | 22 | 0.136 | 0.136 | 0.095 | 0.000-0.274 |
| char_lr | 22 | 0.182 | 0.818 | 0.179 | 0.045-0.364 |
| char_api_lr | 22 | 0.227 | 0.636 | 0.274 | 0.045-0.409 |
| conditional_char_lr (train Y only: 84) | 22 | 0.455 | 0.864 | 0.338 | - |

Constant baselines over the same valid Y rows:

- majority mechanism (checked_api, safe_wrapper, init_memory): top-1 0.000, top-3 0.591
- majority family (memory, checked, safe_api): top-1 0.273, top-3 0.773

Family view of the conditional model (5 families + retain):

| model | top-1 | top-3 | macro-F1 |
|---|---:|---:|---:|
| conditional_char_lr | 0.409 | 0.818 | 0.235 |

Valid Y mechanism support:

- safe_wrapper: 10
- capacity_ops: 3
- init_memory: 3
- unnecessary: 2
- interior_mutability: 2
- restructure: 1
- slice_view: 1
