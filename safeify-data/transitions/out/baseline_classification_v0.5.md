# Unsafe-usage classification (v0.5 data)

Target: the remediation class of an unsafe snippet (`retain` when no safe
replacement exists in that frame). Fit on train, score the frozen valid
split once; test sealed. Metrics are classification metrics.

| model | 11-class acc | 11-class macro F1 | 6-class (family) acc | family macro F1 | binary acc |
|---|---:|---:|---:|---:|---:|
| majority | 0.747 | 0.078 | 0.747 | 0.244 | 0.747 |
| api_lookup | 0.609 | 0.101 | 0.644 | 0.304 | 0.644 |
| char_lr | 0.391 | 0.138 | 0.414 | 0.269 | 0.471 |
| char_api_lr | 0.368 | 0.237 | 0.368 | 0.310 | 0.425 |
| hierarchical | 0.425 | 0.237 | 0.425 | 0.322 | 0.483 |

Bootstrap 95% intervals on valid:

- majority: accuracy 0.655-0.828; macro F1 0.072-0.082
- api_lookup: accuracy 0.517-0.713; macro F1 0.070-0.130
- char_lr: accuracy 0.287-0.494; macro F1 0.072-0.200
- char_api_lr: accuracy 0.264-0.471; macro F1 0.141-0.312
- hierarchical: accuracy 0.333-0.529; macro F1 0.141-0.308

## Per-class view, family level (char_api_lr)

| class | precision | recall | F1 | support |
|---|---:|---:|---:|---:|
| retain | 0.857 | 0.277 | 0.419 | 65 |
| checked | 0.000 | 0.000 | 0.000 | 1 |
| memory | 0.400 | 1.000 | 0.571 | 6 |
| safe_api | 0.222 | 0.400 | 0.286 | 10 |
| ownership | 0.154 | 0.667 | 0.250 | 3 |
| remove | 0.125 | 1.000 | 0.222 | 2 |

## Per-class view, mechanism level (char_api_lr)

| class | precision | recall | F1 | support |
|---|---:|---:|---:|---:|
| slice_view | 0.000 | 0.000 | 0.000 | 1 |
| init_memory | 0.375 | 1.000 | 0.545 | 3 |
| capacity_ops | 0.429 | 1.000 | 0.600 | 3 |
| safe_wrapper | 0.222 | 0.400 | 0.286 | 10 |
| interior_mutability | 0.200 | 0.500 | 0.286 | 2 |
| restructure | 0.143 | 1.000 | 0.250 | 1 |
| unnecessary | 0.125 | 1.000 | 0.222 | 2 |
| retain | 0.857 | 0.277 | 0.419 | 65 |

Most frequent confusions (true -> predicted):

- retain -> safe_wrapper: 13
- retain -> unnecessary: 12
- retain -> restructure: 6
- retain -> init_memory: 5
- retain -> capacity_ops: 4
- retain -> interior_mutability: 3
- safe_wrapper -> unnecessary: 2
- safe_wrapper -> retain: 2
- retain -> checked_api: 2
- slice_view -> safe_wrapper: 1

## Binary collapse (retain vs any mechanism)

- majority: accuracy 0.747 (0.655-0.839), retain F1 0.855, mechanism F1 0.000
- api_lookup: accuracy 0.644 (0.540-0.736), retain F1 0.763, mechanism F1 0.279
- char_lr: accuracy 0.471 (0.368-0.575), retain F1 0.549, mechanism F1 0.361
- char_api_lr: accuracy 0.425 (0.333-0.529), retain F1 0.419, mechanism F1 0.432
- hierarchical: accuracy 0.483 (0.379-0.586), retain F1 0.526, mechanism F1 0.430
