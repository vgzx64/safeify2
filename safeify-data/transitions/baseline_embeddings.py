"""Linear/kNN probes on the frozen ModernBERT-base embeddings (v0.2).

Same protocol as baseline_suite.py: repository-grouped 5-fold CV on train, fit
on train, score valid; test stays sealed (never encoded).

Usage: cd safeify-data/transitions && python baseline_embeddings.py
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
from sklearn.linear_model import LogisticRegression
from sklearn.model_selection import StratifiedGroupKFold
from sklearn.neighbors import KNeighborsClassifier
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler

from baseline_suite import N_FOLDS, SEED, ci, metrics

OUT = Path(__file__).resolve().parent / "out"
NPZ = OUT / "modernbert_base_v0.2.npz"


def cv_and_valid(model_fn, X, y, groups, Xva, yva):
    skf = StratifiedGroupKFold(n_splits=N_FOLDS, shuffle=True, random_state=SEED)
    oof = np.zeros(len(y))
    for fold, (tr, te) in enumerate(skf.split(X, y, groups)):
        model = model_fn(SEED + fold)
        model.fit(X[tr], y[tr])
        oof[te] = model.predict_proba(X[te])[:, 1]
    pooled = metrics(y, oof)
    model = model_fn(SEED)
    model.fit(X, y)
    p = model.predict_proba(Xva)[:, 1]
    return pooled, metrics(yva, p), ci(yva, p)


def main():
    d = np.load(NPZ, allow_pickle=False)
    emb, y, split, repo = d["emb"], d["y"], d["split"], d["repo"]
    assert set(split) == {"train", "valid"}, "test split leaked into embeddings"
    tr, va = split == "train", split == "valid"
    X, ytr, g = emb[tr], y[tr], repo[tr]
    Xva, yva = emb[va], y[va]
    assert not (set(g) & set(repo[va])), "repository leakage"

    models = {
        "linear_emb_C0.01": lambda s: Pipeline([("sc", StandardScaler()),
            ("clf", LogisticRegression(class_weight="balanced", C=0.01,
                                       max_iter=5000, random_state=s))]),
        "linear_emb_C0.1": lambda s: Pipeline([("sc", StandardScaler()),
            ("clf", LogisticRegression(class_weight="balanced", C=0.1,
                                       max_iter=5000, random_state=s))]),
        "linear_emb_C1": lambda s: Pipeline([("sc", StandardScaler()),
            ("clf", LogisticRegression(class_weight="balanced", C=1.0,
                                       max_iter=5000, random_state=s))]),
        "knn_emb_k5": lambda s: KNeighborsClassifier(n_neighbors=5,
            weights="distance", metric="cosine"),
    }

    res = {
        "core": "out/transitions_core_v0.2.jsonl",
        "model": "answerdotai/ModernBERT-base (frozen, mean-pooled, L2-normalised)",
        "protocol": "repo-grouped 5-fold CV on train; fit train; score valid; test sealed",
        "sizes": {"train": int(tr.sum()), "valid": int(va.sum()),
                  "train_pos": int(ytr.sum()), "valid_pos": int(yva.sum())},
        "models": {},
    }
    for name, fn in models.items():
        cv, v, b = cv_and_valid(fn, X, ytr, g, Xva, yva)
        res["models"][name] = {"cv": cv, "valid": v, "valid_ci95": b}
        print(f"{name:18s} cv_f1={cv['f1_Y']:.3f} cv_auc={cv['roc_auc']:.3f} "
              f"valid_f1={v['f1_Y']:.3f} valid_auc={v['roc_auc']:.3f}")

    json.dump(res, open(OUT / "baseline_modernbert_v0.2.json", "w"),
              indent=2, ensure_ascii=False)
    md = ["# ModernBERT-base frozen-embedding probes (v0.2)", "",
          "Repository-grouped 5-fold CV on train; fit on train and score valid; test sealed.",
          "Input: `old_snippet`, frozen mean-pooled embeddings.", "",
          "| probe | CV F1(Y) | CV AUC | valid F1(Y) | valid AUC | valid AP |",
          "|---|---:|---:|---:|---:|---:|"]
    for name, r in res["models"].items():
        cv, v = r["cv"], r["valid"]
        md.append(f"| {name} | {cv['f1_Y']:.3f} | {cv['roc_auc']:.3f} | "
                  f"{v['f1_Y']:.3f} | {v['roc_auc']:.3f} | {v['average_precision']:.3f} |")
    (OUT / "baseline_modernbert_v0.2.md").write_text("\n".join(md) + "\n", encoding="utf-8")
    print(f"wrote {OUT/'baseline_modernbert_v0.2.json'} and .md")


if __name__ == "__main__":
    main()
