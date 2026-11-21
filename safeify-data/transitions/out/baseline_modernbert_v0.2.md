# ModernBERT-base frozen-embedding probes (v0.2)

Repository-grouped 5-fold CV on train; fit on train and score valid; test sealed.
Input: `old_snippet`, frozen mean-pooled embeddings.

| probe | CV F1(Y) | CV AUC | valid F1(Y) | valid AUC | valid AP |
|---|---:|---:|---:|---:|---:|
| linear_emb_C0.01 | 0.508 | 0.716 | 0.400 | 0.631 | 0.412 |
| linear_emb_C0.1 | 0.453 | 0.672 | 0.400 | 0.634 | 0.412 |
| linear_emb_C1 | 0.425 | 0.642 | 0.400 | 0.632 | 0.412 |
| knn_emb_k5 | 0.298 | 0.553 | 0.273 | 0.534 | 0.282 |
