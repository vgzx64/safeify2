# Hazard classification (v0.5 labels, rule-derived)

Predict the site's hazard class from `old_snippet` + `api_guess`. Rows whose
unsafe operation is only a delegated call (`unsafe_call`) or undeterminable
(`unknown`) are excluded from the primary task and reported as coverage.
Fit on train, score the frozen valid split once; test sealed.

| task | train rows | valid rows | accuracy | macro F1 |
|---|---:|---:|---:|---:|
| 10 hazards | 418 | 68 | 0.779 | 0.592 |
| 12 classes | 745 | 87 | 0.759 | 0.574 |

Coverage of determinable hazards: train 0.561, valid 0.782.

## Per-class, 10-hazard task

| hazard | precision | recall | F1 | support |
|---|---:|---:|---:|---:|
| raw_ownership | 1.000 | 0.667 | 0.800 | 15 |
| manual_capacity | 0.667 | 1.000 | 0.800 | 4 |
| raw_memory | 0.625 | 1.000 | 0.769 | 5 |
| uninit_memory | 1.000 | 0.727 | 0.842 | 11 |
| reinterpret | 1.000 | 0.333 | 0.500 | 3 |
| raw_deref | 0.500 | 1.000 | 0.667 | 8 |
| unchecked_index | 0.000 | 0.000 | 0.000 | 1 |
| ffi_boundary | 1.000 | 0.400 | 0.571 | 5 |
| unsafe_trait | 0.938 | 1.000 | 0.968 | 15 |
| unsafe_contract | 0.000 | 0.000 | 0.000 | 1 |

Top confusions:

- uninit_memory -> raw_deref: 3
- ffi_boundary -> raw_deref: 3
- raw_ownership -> manual_capacity: 2
- raw_ownership -> raw_memory: 2
- raw_ownership -> unsafe_contract: 1
- reinterpret -> raw_memory: 1
- reinterpret -> raw_deref: 1
- unchecked_index -> unsafe_trait: 1

Bootstrap 95% CI (10-hazard): accuracy 0.676-0.868, macro F1 0.455-0.676.

Grouped CV (train): accuracy 0.658, macro F1 0.612.
