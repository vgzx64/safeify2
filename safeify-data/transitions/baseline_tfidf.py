"""Smoke-test baseline: binary `Y` vs `{N,M}` on old snippets.

Trained on the train split and evaluated on valid only. The test split stays
sealed until the dataset is frozen. This measures whether the labels carry a
learnable signal at all, not a headline model.
"""

from __future__ import annotations

import json
from collections import Counter
from pathlib import Path

from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import (
    accuracy_score,
    confusion_matrix,
    f1_score,
    precision_score,
    recall_score,
    roc_auc_score,
)
from sklearn.pipeline import make_pipeline

OUT = Path(__file__).resolve().parent / "out"
CORE = OUT / "transitions_core_v0.2_draft.jsonl"


def split(rows, name):
    return [r for r in rows if r["split"] == name]


def xy(rows):
    return [r.get("old_snippet") or "" for r in rows], [1 if r["label"] == "Y" else 0 for r in rows]


def main() -> int:
    rows = [json.loads(x) for x in CORE.open() if x.strip()]
    train, valid = split(rows, "train"), split(rows, "valid")
    xtr, ytr = xy(train)
    xva, yva = xy(valid)

    model = make_pipeline(
        TfidfVectorizer(analyzer="char_wb", ngram_range=(2, 5), min_df=2, sublinear_tf=True),
        LogisticRegression(max_iter=2000, class_weight="balanced"),
    )
    model.fit(xtr, ytr)
    proba = model.predict_proba(xva)[:, 1]
    pred = [int(p >= 0.5) for p in proba]
    tn, fp, fn, tp = confusion_matrix(yva, pred, labels=[0, 1]).ravel()

    report = {
        "model": "TF-IDF char_wb(2,5) + logistic regression (class_weight=balanced)",
        "input": "old_snippet only",
        "label": "Y vs {N,M}",
        "train": {"rows": len(train), "positives": sum(ytr)},
        "valid": {"rows": len(valid), "positives": sum(yva)},
        "valid_majority_accuracy": max(Counter(yva).values()) / len(yva),
        "valid_metrics": {
            "accuracy": round(accuracy_score(yva, pred), 3),
            "precision_Y": round(precision_score(yva, pred, zero_division=0), 3),
            "recall_Y": round(recall_score(yva, pred, zero_division=0), 3),
            "f1_Y": round(f1_score(yva, pred, zero_division=0), 3),
            "roc_auc": round(roc_auc_score(yva, proba), 3) if len(set(yva)) > 1 else None,
        },
        "confusion": {"tn": int(tn), "fp": int(fp), "fn": int(fn), "tp": int(tp)},
        "test_split_evaluated": False,
        "caveat": "smoke test on 87 valid rows; not a model-quality claim",
    }
    (OUT / "baseline_valid.json").write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
