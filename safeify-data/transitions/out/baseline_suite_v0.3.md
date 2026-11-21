# Transition-core baseline suite (v0.3)

Repository-grouped 5-fold CV on train; fit on train and score valid; test sealed.
Input: `old_snippet` only. Positive class: Y (safe replacement exists).

| model | CV acc | CV F1(Y) | CV AUC | valid acc | valid F1(Y) | valid AUC | valid AP |
|---|---:|---:|---:|---:|---:|---:|---:|
| majority | 0.817 | 0.000 | 0.500 | 0.747 | 0.000 | 0.500 | 0.253 |
| tfidf_word_lr | 0.813 | 0.394 | 0.715 | 0.770 | 0.412 | 0.569 | 0.347 |
| tfidf_char_lr | 0.828 | 0.484 | 0.762 | 0.770 | 0.444 | 0.624 | 0.392 |
| tfidf_union_lr | 0.843 | 0.507 | 0.783 | 0.747 | 0.353 | 0.598 | 0.361 |
| tfidf_svd_hgb | 0.749 | 0.277 | 0.608 | 0.713 | 0.286 | 0.497 | 0.357 |
| tfidf_svd_rf | 0.828 | 0.168 | 0.698 | 0.736 | 0.148 | 0.564 | 0.326 |

95% bootstrap CIs on valid (2.5-97.5 pct):

- majority: F1 0.000-0.000; AUC 0.500-0.500; AP 0.172-0.345
- tfidf_word_lr: F1 0.174-0.595; AUC 0.425-0.702; AP 0.205-0.554
- tfidf_char_lr: F1 0.214-0.622; AUC 0.483-0.761; AP 0.237-0.613
- tfidf_union_lr: F1 0.138-0.541; AUC 0.458-0.732; AP 0.215-0.572
- tfidf_svd_hgb: F1 0.071-0.474; AUC 0.342-0.644; AP 0.190-0.539
- tfidf_svd_rf: F1 0.000-0.333; AUC 0.421-0.704; AP 0.195-0.525
