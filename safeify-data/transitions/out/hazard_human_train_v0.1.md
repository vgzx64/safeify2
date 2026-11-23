# Hazard classifier — human-supervised run

Train labels: 300 blind human hazard labels. Valid: 87 human labels. Both models are scored on the same
human valid labels; test stays sealed.

| training labels | task | train rows | valid rows | accuracy | macro F1 |
|---|---|---:|---:|---:|---:|
| rule_trained_10 | 10 classes | 418 | 79 | 0.684 | 0.519 |
| human_trained_10 | 10 classes | 262 | 79 | 0.696 | 0.550 |
| human_trained_12 | 12 classes | 300 | 87 | 0.690 | 0.502 |

Rules vs human valid labels: 0.793.

Grouped CV on the training labels (human labels, 10-class): accuracy 0.630, macro F1 0.637.

## Per class (human-trained, 10-class, vs human valid)

| hazard | precision | recall | F1 | support |
|---|---:|---:|---:|---:|
| raw_ownership | 0.900 | 0.750 | 0.818 | 12 |
| manual_capacity | 0.833 | 1.000 | 0.909 | 5 |
| raw_memory | 0.714 | 0.714 | 0.714 | 7 |
| uninit_memory | 1.000 | 0.667 | 0.800 | 12 |
| reinterpret | 1.000 | 0.200 | 0.333 | 5 |
| raw_deref | 0.450 | 1.000 | 0.621 | 9 |
| unchecked_index | 0.000 | 0.000 | 0.000 | 0 |
| ffi_boundary | 0.750 | 0.214 | 0.333 | 14 |
| unsafe_trait | 0.938 | 1.000 | 0.968 | 15 |
| unsafe_contract | 0.000 | 0.000 | 0.000 | 0 |

Top confusions:

- ffi_boundary -> raw_deref: 5
- ffi_boundary -> unsafe_contract: 5
- uninit_memory -> raw_deref: 3
- reinterpret -> raw_deref: 2
- raw_ownership -> manual_capacity: 1
- raw_ownership -> raw_memory: 1
- raw_ownership -> unsafe_contract: 1
- raw_memory -> raw_deref: 1
- raw_memory -> unsafe_contract: 1
- uninit_memory -> raw_memory: 1
