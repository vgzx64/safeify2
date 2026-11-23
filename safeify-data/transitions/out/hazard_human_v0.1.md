# Hazard labels: human evaluation (valid split)

Human labels collected for 87 of 87 valid rows.

## Rules vs human annotators

- agreement 0.793, Cohen kappa 0.765 on 87 rows

## Model (trained on rule labels) vs human labels

- rows 79, accuracy 0.684, macro F1 0.519

| hazard | precision | recall | F1 | support |
|---|---:|---:|---:|---:|
| raw_ownership | 0.900 | 0.750 | 0.818 | 12 |
| manual_capacity | 0.833 | 1.000 | 0.909 | 5 |
| raw_memory | 0.625 | 0.714 | 0.667 | 7 |
| uninit_memory | 1.000 | 0.667 | 0.800 | 12 |
| reinterpret | 1.000 | 0.200 | 0.333 | 5 |
| raw_deref | 0.429 | 1.000 | 0.600 | 9 |
| unchecked_index | 0.000 | 0.000 | 0.000 | 0 |
| ffi_boundary | 1.000 | 0.143 | 0.250 | 14 |
| unsafe_trait | 0.682 | 1.000 | 0.811 | 15 |
| unsafe_contract | 0.000 | 0.000 | 0.000 | 0 |

Model vs rule labels on the same rows: accuracy 0.671, macro F1 0.565.

Top confusions against human labels:

- ffi_boundary -> raw_deref: 6
- ffi_boundary -> unsafe_trait: 6
- uninit_memory -> raw_deref: 3
- reinterpret -> raw_deref: 2
- raw_ownership -> manual_capacity: 1
- raw_ownership -> raw_memory: 1
- raw_ownership -> unsafe_contract: 1
- raw_memory -> raw_deref: 1
- raw_memory -> unsafe_trait: 1
- uninit_memory -> raw_memory: 1
