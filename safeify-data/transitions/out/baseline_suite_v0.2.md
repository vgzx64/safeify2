# Transition-core baseline suite (v0.2)

Repository-grouped 5-fold CV on train; fit on train and score valid; test sealed.
Input: `old_snippet` only. Positive class: Y (safe replacement exists).

| model | CV acc | CV F1(Y) | CV AUC | valid acc | valid F1(Y) | valid AUC | valid AP |
|---|---:|---:|---:|---:|---:|---:|---:|
| majority | 0.750 | 0.000 | 0.500 | 0.747 | 0.000 | 0.500 | 0.253 |
| tfidf_word_lr | 0.755 | 0.475 | 0.716 | 0.667 | 0.256 | 0.544 | 0.317 |
| tfidf_char_lr | 0.870 | 0.714 | 0.868 | 0.736 | 0.378 | 0.641 | 0.397 |
| tfidf_union_lr | 0.866 | 0.701 | 0.833 | 0.724 | 0.333 | 0.579 | 0.343 |
| tfidf_svd_hgb | 0.708 | 0.376 | 0.582 | 0.713 | 0.138 | 0.601 | 0.335 |
| tfidf_svd_rf | 0.671 | 0.165 | 0.563 | 0.713 | 0.000 | 0.559 | 0.302 |

95% bootstrap CIs on valid (2.5-97.5 pct):

- majority: F1 0.000-0.000; AUC 0.500-0.500; AP 0.172-0.345
- tfidf_word_lr: F1 0.062-0.429; AUC 0.394-0.687; AP 0.192-0.509
- tfidf_char_lr: F1 0.160-0.560; AUC 0.494-0.776; AP 0.252-0.615
- tfidf_union_lr: F1 0.125-0.524; AUC 0.431-0.716; AP 0.210-0.555
- tfidf_svd_hgb: F1 0.000-0.308; AUC 0.464-0.721; AP 0.206-0.532
- tfidf_svd_rf: F1 0.000-0.000; AUC 0.418-0.699; AP 0.193-0.474
