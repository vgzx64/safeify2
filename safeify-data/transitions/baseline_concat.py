"""Char TF-IDF + frozen ModernBERT embeddings, concatenated (v0.2).

A cheap complementarity probe: does the lexical (char n-gram) view add to the
frozen encoder view, or vice versa? Same protocol: repo-grouped 5-fold CV on
train, fit on train, score valid; test sealed (not encoded).

Usage: cd safeify-data/transitions && python baseline_concat.py
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
from scipy.sparse import csr_matrix, hstack
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.linear_model import LogisticRegression
from sklearn.model_selection import StratifiedGroupKFold
from sklearn.preprocessing import StandardScaler

from baseline_suite import N_FOLDS, SEED, ci, metrics

OUT = Path(__file__).resolve().parent / "out"
CORE = OUT / "transitions_core_v0.2.jsonl"
NPZ = OUT / "modernbert_base_v0.2.npz"
EMB_WEIGHT = 0.5


def build(train_idx, test_idx, texts, emb, y, C):
    tf = TfidfVectorizer(analyzer="char_wb", ngram_range=(2, 5),
                         sublinear_tf=True, min_df=2)
    tt = tf.fit_transform([texts[i] for i in train_idx])
    te = tf.transform([texts[i] for i in test_idx])
    sc = StandardScaler().fit(emb[train_idx])
    et = sc.transform(emb[train_idx]) * EMB_WEIGHT
    ee = sc.transform(emb[test_idx]) * EMB_WEIGHT
    Xt = hstack([tt, csr_matrix(et)]).tocsr()
    Xe = hstack([te, csr_matrix(ee)]).tocsr()
    clf = LogisticRegression(class_weight="balanced", C=C, max_iter=5000,
                             random_state=SEED)
    clf.fit(Xt, y[train_idx])
    return clf.predict_proba(Xe)[:, 1]


def main():
    d = np.load(NPZ, allow_pickle=False)
    emb, split, repo, ids = d["emb"], d["split"], d["repo"], d["ids"]
    core = {r["id"]: r for r in
            (json.loads(line) for line in open(CORE, encoding="utf-8") if line.strip())}
    texts = [core[i]["old_snippet"] for i in ids]
    y = np.array([core[i]["target"] for i in ids])
    assert set(split) == {"train", "valid"}
    tr = np.flatnonzero(split == "train")
    va = np.flatnonzero(split == "valid")
    ytr, yva = y[tr], y[va]
    assert not (set(repo[tr]) & set(repo[va]))

    res = {"core": "out/transitions_core_v0.2.jsonl", "input": "char TF-IDF + frozen ModernBERT-base (weight 0.5)",
           "protocol": "repo-grouped 5-fold CV on train; fit train; score valid; test sealed",
           "models": {}}
    for C in (0.1, 1.0):
        skf = StratifiedGroupKFold(n_splits=N_FOLDS, shuffle=True, random_state=SEED)
        oof = np.zeros(len(tr))
        for fold, (a, b) in enumerate(skf.split(tr, ytr, repo[tr])):
            oof[b] = build(tr[a], tr[b], texts, emb, y, C)
        # valid: fit on all train, predict valid
        p_va = build(tr, va, texts, emb, y, C)
        name = f"char_plus_emb_C{C}"
        res["models"][name] = {"cv": metrics(ytr, oof),
                               "valid": metrics(yva, p_va), "valid_ci95": ci(yva, p_va)}
        cv, v = res["models"][name]["cv"], res["models"][name]["valid"]
        print(f"{name:18s} cv_f1={cv['f1_Y']:.3f} cv_auc={cv['roc_auc']:.3f} "
              f"valid_f1={v['f1_Y']:.3f} valid_auc={v['roc_auc']:.3f}")

    json.dump(res, open(OUT / "baseline_concat_v0.2.json", "w"), indent=2)
    md = ["# Char TF-IDF + ModernBERT embeddings (v0.2)", "",
          "Repository-grouped 5-fold CV on train; fit on train and score valid; test sealed.", "",
          "| probe | CV F1(Y) | CV AUC | valid F1(Y) | valid AUC | valid AP |",
          "|---|---:|---:|---:|---:|---:|"]
    for name, r in res["models"].items():
        cv, v = r["cv"], r["valid"]
        md.append(f"| {name} | {cv['f1_Y']:.3f} | {cv['roc_auc']:.3f} | "
                  f"{v['f1_Y']:.3f} | {v['roc_auc']:.3f} | {v['average_precision']:.3f} |")
    (OUT / "baseline_concat_v0.2.md").write_text("\n".join(md) + "\n", encoding="utf-8")
    print(f"wrote {OUT/'baseline_concat_v0.2.json'} and .md")


if __name__ == "__main__":
    main()
