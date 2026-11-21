"""Baseline suite for the frozen transition core (v0.2) and drafts (v0.3+).

Question: does the binary replaceability target (`safe_replaceable`: Y=1,
M/N=0) carry a learnable signal from the vulnerable snippet alone, and does the
formal NIRM 4 toolset (Gradient Boosting / Random Forest) beat the cheap text
baselines?

Protocol (same as the rest of the track):
  * rows: out/transitions_core_v0.2.jsonl (frozen) or a v0.3 draft; the
    frozen valid/test sizes are asserted either way
  * input: `old_snippet` ONLY -- the fix (`safe_snippet`) and the diff
    (`deleted_lines`/`added_lines`, present on one row each) are excluded
  * selection: repository-grouped 5-fold CV on `train` (groups = `repo_key`)
  * report: fit on `train`, score `valid`
  * `test` stays sealed: it is loaded only for the size assertion and is never
    vectorised or scored.

Writes out/baseline_suite_<version>.json and .md.
Usage: cd safeify-data/transitions && python baseline_suite.py
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
from sklearn.dummy import DummyClassifier
from sklearn.ensemble import HistGradientBoostingClassifier, RandomForestClassifier
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import (accuracy_score, average_precision_score,
                             confusion_matrix, f1_score, precision_score,
                             recall_score, roc_auc_score)
from sklearn.model_selection import StratifiedGroupKFold
from sklearn.pipeline import FeatureUnion, Pipeline
from sklearn.decomposition import TruncatedSVD

OUT = Path(__file__).resolve().parent / "out"
SEED = 0
N_FOLDS = 5
N_BOOT = 2000
BIN_LABELS = (0, 1)

MODELS = {
    "majority": lambda seed: DummyClassifier(strategy="most_frequent"),
    "tfidf_word_lr": lambda seed: Pipeline([
        ("tfidf", TfidfVectorizer(ngram_range=(1, 2), sublinear_tf=True,
                                  min_df=1, strip_accents=None)),
        ("clf", LogisticRegression(class_weight="balanced", max_iter=2000,
                                   C=1.0, random_state=seed)),
    ]),
    "tfidf_char_lr": lambda seed: Pipeline([
        ("tfidf", TfidfVectorizer(analyzer="char_wb", ngram_range=(2, 5),
                                  sublinear_tf=True, min_df=2)),
        ("clf", LogisticRegression(class_weight="balanced", max_iter=2000,
                                   C=1.0, random_state=seed)),
    ]),
    "tfidf_union_lr": lambda seed: Pipeline([
        ("feat", FeatureUnion([
            ("word", TfidfVectorizer(ngram_range=(1, 2), sublinear_tf=True)),
            ("char", TfidfVectorizer(analyzer="char_wb", ngram_range=(2, 5),
                                     sublinear_tf=True, min_df=2)),
        ])),
        ("clf", LogisticRegression(class_weight="balanced", max_iter=3000,
                                   C=1.0, random_state=seed)),
    ]),
    "tfidf_svd_hgb": lambda seed: Pipeline([
        ("tfidf", TfidfVectorizer(ngram_range=(1, 2), sublinear_tf=True)),
        ("svd", TruncatedSVD(n_components=64, random_state=seed)),
        ("clf", HistGradientBoostingClassifier(
            max_iter=300, learning_rate=0.05, max_leaf_nodes=15,
            l2_regularization=1.0, class_weight="balanced",
            random_state=seed)),
    ]),
    "tfidf_svd_rf": lambda seed: Pipeline([
        ("tfidf", TfidfVectorizer(ngram_range=(1, 2), sublinear_tf=True)),
        ("svd", TruncatedSVD(n_components=64, random_state=seed)),
        ("clf", RandomForestClassifier(
            n_estimators=500, min_samples_leaf=2,
            class_weight="balanced_subsample", n_jobs=-1,
            random_state=seed)),
    ]),
}


def load_rows(core: Path, frozen: bool):
    rows = [json.loads(line) for line in open(core, encoding="utf-8") if line.strip()]
    if frozen:
        assert all(r.get("frozen") is True for r in rows), "core is not frozen"
    assert all(r["target"] in BIN_LABELS for r in rows), "bad target"
    assert all(r.get("old_snippet") for r in rows), "missing input text"
    train = [r for r in rows if r["split"] == "train"]
    valid = [r for r in rows if r["split"] == "valid"]
    test = [r for r in rows if r["split"] == "test"]
    if frozen:
        assert (len(train), len(valid), len(test)) == (216, 87, 130)
    else:
        assert len(train) > 216 and len(valid) == 87 and len(test) == 130, \
            "a draft must keep the frozen valid/test sizes"
    repos = [{r["repo_key"] for r in part} for part in (train, valid, test)]
    assert not (repos[0] & repos[1]) and not (repos[0] & repos[2]) \
        and not (repos[1] & repos[2]), "repository leakage across splits"
    return train, valid, test


def metrics(y, p, pred=None):
    y = np.asarray(y)
    p = np.asarray(p, dtype=float)
    pred = (p >= 0.5).astype(int) if pred is None else np.asarray(pred)
    out = {
        "n": int(len(y)),
        "positives": int(y.sum()),
        "accuracy": accuracy_score(y, pred),
        "precision_Y": precision_score(y, pred, pos_label=1, zero_division=0),
        "recall_Y": recall_score(y, pred, pos_label=1, zero_division=0),
        "f1_Y": f1_score(y, pred, pos_label=1, zero_division=0),
        "roc_auc": float(roc_auc_score(y, p)) if y.min() != y.max() else None,
        "average_precision": float(average_precision_score(y, p)) if y.min() != y.max() else None,
        "confusion": confusion_matrix(y, pred, labels=BIN_LABELS).tolist(),
    }
    return out


def ci(y, p):
    y = np.asarray(y)
    p = np.asarray(p, dtype=float)
    rng = np.random.default_rng(1234)
    f1s, aucs, aps = [], [], []
    for _ in range(N_BOOT):
        idx = rng.integers(0, len(y), len(y))
        yy, pp = y[idx], p[idx]
        pred = (pp >= 0.5).astype(int)
        f1s.append(f1_score(yy, pred, pos_label=1, zero_division=0))
        if yy.min() != yy.max():
            aucs.append(roc_auc_score(yy, pp))
            aps.append(average_precision_score(yy, pp))
    def band(values):
        v = np.asarray(values, dtype=float)
        return [float(np.percentile(v, 2.5)), float(np.percentile(v, 97.5))]
    return {"f1_Y": band(f1s),
            "roc_auc": band(aucs) if aucs else None,
            "average_precision": band(aps) if aps else None}


def cv_scores(name, rows):
    texts = [r["old_snippet"] for r in rows]
    y = np.array([r["target"] for r in rows])
    groups = np.array([r["repo_key"] for r in rows])
    skf = StratifiedGroupKFold(n_splits=N_FOLDS, shuffle=True, random_state=SEED)
    oof = np.zeros(len(y))
    folds = []
    for fold, (tr, te) in enumerate(skf.split(texts, y, groups)):
        model = MODELS[name](SEED + fold)
        model.fit([texts[i] for i in tr], y[tr])
        p = model.predict_proba([texts[i] for i in te])[:, 1]
        oof[te] = p
        f = metrics(y[te], p)
        f["fold"] = fold
        folds.append(f)
    pooled = metrics(y, oof)
    pooled["fold_mean_f1_Y"] = float(np.mean([f["f1_Y"] for f in folds]))
    pooled["fold_sd_f1_Y"] = float(np.std([f["f1_Y"] for f in folds]))
    aucs = [f["roc_auc"] for f in folds if f["roc_auc"] is not None]
    pooled["fold_mean_roc_auc"] = float(np.mean(aucs)) if aucs else None
    pooled["fold_sd_roc_auc"] = float(np.std(aucs)) if aucs else None
    pooled["folds"] = folds
    return pooled, oof


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--version", default="v0.2",
                    help="v0.2 (frozen) or a draft version such as v0.3")
    args = ap.parse_args()
    frozen = args.version == "v0.2"
    core = OUT / f"transitions_core_{args.version}{'' if frozen else '_draft'}.jsonl"
    train, valid, test = load_rows(core, frozen)
    ytr = np.array([r["target"] for r in train])
    yva = np.array([r["target"] for r in valid])
    xva = [r["old_snippet"] for r in valid]
    xtr = [r["old_snippet"] for r in train]

    results = {
        "core": str(core.relative_to(core.parent.parent.parent)),
        "protocol": "repo-grouped 5-fold CV on train; fit train; score valid; test sealed",
        "seed": SEED,
        "sizes": {"train": len(train), "valid": len(valid), "test_sealed": len(test),
                  "train_pos": int(ytr.sum()), "valid_pos": int(yva.sum())},
        "input": "old_snippet only (no safe_snippet, no diff, no summary)",
        "models": {},
    }
    for name in MODELS:
        pooled, _ = cv_scores(name, train)
        model = MODELS[name](SEED)
        model.fit(xtr, ytr)
        p = model.predict_proba(xva)[:, 1]
        res = {"cv": pooled, "valid": metrics(yva, p), "valid_ci95": ci(yva, p)}
        results["models"][name] = res
        print(f"{name:18s} cv_f1={pooled['f1_Y']:.3f} cv_auc={pooled['roc_auc']:.3f} "
              f"valid_f1={res['valid']['f1_Y']:.3f} valid_auc={res['valid']['roc_auc']:.3f}")

    json.dump(results, open(OUT / f"baseline_suite_{args.version}.json", "w"),
              indent=2, ensure_ascii=False)

    md = [f"# Transition-core baseline suite ({args.version})", "",
          "Repository-grouped 5-fold CV on train; fit on train and score valid; test sealed.",
          "Input: `old_snippet` only. Positive class: Y (safe replacement exists).", "",
          "| model | CV acc | CV F1(Y) | CV AUC | valid acc | valid F1(Y) | valid AUC | valid AP |",
          "|---|---:|---:|---:|---:|---:|---:|---:|"]
    for name, r in results["models"].items():
        cv, v = r["cv"], r["valid"]
        md.append(f"| {name} | {cv['accuracy']:.3f} | {cv['f1_Y']:.3f} | "
                  f"{cv['roc_auc']:.3f} | {v['accuracy']:.3f} | {v['f1_Y']:.3f} | "
                  f"{v['roc_auc']:.3f} | {v['average_precision']:.3f} |")
    md += ["", "95% bootstrap CIs on valid (2.5-97.5 pct):", ""]
    for name, r in results["models"].items():
        b = r["valid_ci95"]
        auc = b["roc_auc"]
        md.append(f"- {name}: F1 {b['f1_Y'][0]:.3f}-{b['f1_Y'][1]:.3f}; "
                  f"AUC {auc[0]:.3f}-{auc[1]:.3f}; "
                  f"AP {b['average_precision'][0]:.3f}-{b['average_precision'][1]:.3f}")
    (OUT / f"baseline_suite_{args.version}.md").write_text("\n".join(md) + "\n", encoding="utf-8")
    print(f"\nwrote {OUT}/baseline_suite_{args.version}.json and .md")


if __name__ == "__main__":
    main()
