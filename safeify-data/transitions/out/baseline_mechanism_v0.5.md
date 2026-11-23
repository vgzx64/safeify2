# Mechanism classification baseline (v0.5)

Fit on train (459) and score the frozen valid split (87); test sealed.
Input: `old_snippet` + `api_guess`; positive-task mechanics: predict the
safe-remediation mechanism, or `retain` when unsafe stays (M/N).

## Joint task (mechanism or retain)

| model | valid acc | valid macro-F1 | mechanism suggested on M/N | retain predicted on Y |
|---|---:|---:|---:|---:|
| majority | 0.747 | 0.107 | 0 | 22 |
| api_lookup | 0.609 | 0.112 | 15 | 16 |
| char_lr | 0.391 | 0.169 | 37 | 9 |
| char_api_lr | 0.368 | 0.261 | 47 | 3 |

## Conditional on Y rows (which mechanism)

| model | n | top-1 | top-3 | macro-F1 | 95% CI top-1 |
|---|---:|---:|---:|---:|---:|
| majority | 22 | 0.000 | 0.136 | 0.000 | 0.000-0.000 |
| api_lookup | 22 | 0.136 | 0.136 | 0.095 | 0.000-0.274 |
| char_lr | 22 | 0.273 | 0.818 | 0.345 | 0.091-0.455 |
| char_api_lr | 22 | 0.636 | 0.909 | 0.671 | 0.453-0.818 |
| conditional_char_lr (train Y only: 318) | 22 | 0.591 | 0.864 | 0.480 | - |

Constant baselines over the same valid Y rows:

- majority mechanism (safe_wrapper, restructure, checked_api): top-1 0.455, top-3 0.500
- majority family (ownership, safe_api, checked): top-1 0.136, top-3 0.636

Family view of the conditional model (5 families + retain):

| model | top-1 | top-3 | macro-F1 |
|---|---:|---:|---:|
| conditional_char_lr | 0.682 | 0.955 | 0.502 |

Valid Y mechanism support:

- safe_wrapper: 10
- capacity_ops: 3
- init_memory: 3
- unnecessary: 2
- interior_mutability: 2
- restructure: 1
- slice_view: 1
