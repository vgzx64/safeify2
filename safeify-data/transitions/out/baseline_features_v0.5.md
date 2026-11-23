# Feature-based classification of unsafe usage (v0.5)

Binary target: does a safe remediation exist (retain vs mechanism)?
Multiclass: which remediation class. Fit on train; frozen valid scored once.

| variant | binary AUC | binary acc | AP | multi acc | multi macro-F1 |
|---|---:|---:|---:|---:|---:|
| feat_lr | 0.557 | 0.586 | 0.285 | 0.172 | 0.107 |
| feat_api_lr | 0.557 | 0.586 | 0.285 | 0.172 | 0.107 |
| feat_text_lr | 0.565 | 0.540 | 0.293 | 0.345 | 0.205 |
| feat_api_text_lr | 0.565 | 0.540 | 0.293 | 0.345 | 0.205 |
| feat_gb | 0.655 | 0.632 | 0.366 | 0.563 | 0.126 |
| text_api_lr | 0.610 | 0.586 | 0.412 | 0.368 | 0.237 |

Bootstrap 95% CI on valid (binary AUC / accuracy):

- feat_lr: AUC 0.419-0.693, accuracy 0.483-0.690
- feat_api_lr: AUC 0.419-0.693, accuracy 0.483-0.690
- feat_text_lr: AUC 0.423-0.705, accuracy 0.437-0.644
- feat_api_text_lr: AUC 0.423-0.705, accuracy 0.437-0.644
- feat_gb: AUC 0.529-0.779, accuracy 0.529-0.724
- text_api_lr: AUC 0.469-0.737, accuracy 0.483-0.690

Grouped CV (train):

- feat_lr: binary CV AUC 0.700, acc 0.636; multi CV macro-F1 0.256
- feat_api_text_lr: binary CV AUC 0.704, acc 0.604; multi CV macro-F1 0.267
