# Char TF-IDF + ModernBERT embeddings (v0.2)

Repository-grouped 5-fold CV on train; fit on train and score valid; test sealed.

| probe | CV F1(Y) | CV AUC | valid F1(Y) | valid AUC | valid AP |
|---|---:|---:|---:|---:|---:|
| char_plus_emb_C0.1 | 0.458 | 0.699 | 0.391 | 0.633 | 0.415 |
| char_plus_emb_C1.0 | 0.441 | 0.663 | 0.400 | 0.633 | 0.410 |
