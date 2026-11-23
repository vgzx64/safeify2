"""Feature-based classifier for unsafe-code usage (v0.5 data).

Primary question: does an unsafe site have a safe remediation at all?
(binary: retain vs any mechanism). Secondary: which remediation class
(multiclass, same classes as the mechanism model).

Compares hand-built fingerprint features (unsafe API, FFI, pointer use,
manual-length/initialisation shape) against character n-grams, and the union of
both. Grouped 5-fold CV on train; frozen valid split scored once; test sealed.

Writes out/baseline_features_v0.5.{json,md}.
"""

from __future__ import annotations

import json
from collections import Counter
from pathlib import Path

import numpy as np
from sklearn.base import BaseEstimator, TransformerMixin
from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import (accuracy_score, average_precision_score,
                             f1_score, precision_score, recall_score, roc_auc_score)
from sklearn.model_selection import StratifiedGroupKFold
from sklearn.pipeline import FeatureUnion, Pipeline
from sklearn.preprocessing import OneHotEncoder, StandardScaler

from baseline_mechanism import MECH
from features_unsafe import feature_matrix

OUT = Path(__file__).resolve().parent / "out"
DATASET = OUT / "mechanism_dataset_v05.jsonl"
SEED = 0
N_BOOT = 2000


def load():
    rows = [json.loads(x) for x in DATASET.open() if x.strip()]
    train = [r for r in rows if r["split"] == "train"]
    valid = [r for r in rows if r["split"] == "valid"]
    test = [r for r in rows if r["split"] == "test"]
    assert (len(valid), len(test)) == (87, 130)
    return train, valid


def as_inputs(rows):
    return [{"old_snippet": r["old_snippet"], "api_guess": r.get("api_guess") or "unknown"}
            for r in rows]


class NumericFeatures(BaseEstimator, TransformerMixin):
    def fit(self, x, y=None):
        return self

    def transform(self, x):
        matrix, _ = feature_matrix(x)
        return matrix


class SelectText(BaseEstimator, TransformerMixin):
    def fit(self, x, y=None):
        return self

    def transform(self, x):
        return [r["old_snippet"] for r in x]


class SelectApi(BaseEstimator, TransformerMixin):
    def fit(self, x, y=None):
        return self

    def transform(self, x):
        return [[r.get("api_guess") or "unknown"] for r in x]


def branches(use_features=True, use_text=False, use_api=True):
    out = []
    if use_features:
        out.append(("num", Pipeline([("num", NumericFeatures()), ("sc", StandardScaler())])))
    if use_text:
        out.append(("tfidf", Pipeline([
            ("sel", SelectText()),
            ("tfidf", TfidfVectorizer(analyzer="char_wb", ngram_range=(2, 5),
                                      sublinear_tf=True, min_df=2)),
        ])))
    if use_api:
        out.append(("api", Pipeline([("sel", SelectApi()),
                                     ("oh", OneHotEncoder(handle_unknown="ignore"))])))
    return out


def make_model(features=True, text=False, api=True, clf="lr"):
    feats = FeatureUnion(branches(features, text, api))
    if clf == "lr":
        clf_obj = LogisticRegression(class_weight="balanced", max_iter=3000,
                                     C=1.0, random_state=SEED)
    else:
        clf_obj = HistGradientBoostingClassifier(max_iter=300, learning_rate=0.05,
                                                 max_leaf_nodes=15, l2_regularization=1.0,
                                                 random_state=SEED)
    return Pipeline([("feat", feats), ("clf", clf_obj)])


def binary_metrics(rows, proba):
    y = np.array([r["mechanism"] != "retain" for r in rows])
    pred = proba >= 0.5
    out = {
        "n": len(y), "positives": int(y.sum()),
        "roc_auc": float(roc_auc_score(y, proba)),
        "average_precision": float(average_precision_score(y, proba)),
        "accuracy": float(accuracy_score(y, pred)),
        "macro_f1": float(f1_score(y, pred, average="macro", zero_division=0)),
        "precision_mechanism": float(precision_score(y, pred, zero_division=0)),
        "recall_mechanism": float(recall_score(y, pred, zero_division=0)),
    }
    rng = np.random.default_rng(7)
    aucs, accs = [], []
    for _ in range(N_BOOT):
        idx = rng.integers(0, len(y), len(y))
        if y[idx].min() == y[idx].max():
            continue
        aucs.append(roc_auc_score(y[idx], proba[idx]))
        accs.append(accuracy_score(y[idx], pred[idx]))
    out["ci95"] = {"roc_auc": [float(np.percentile(aucs, 2.5)), float(np.percentile(aucs, 97.5))],
                   "accuracy": [float(np.percentile(accs, 2.5)), float(np.percentile(accs, 97.5))]}
    return out


def multi_metrics(rows, proba, classes):
    y = np.array([r["mechanism"] for r in rows])
    pred = np.array([classes[i] for i in proba.argmax(axis=1)])
    out = {"accuracy": float(accuracy_score(y, pred)),
           "macro_f1": float(f1_score(y, pred, labels=MECH, average="macro",
                                      zero_division=0)),
           "weighted_f1": float(f1_score(y, pred, labels=MECH, average="weighted",
                                         zero_division=0))}
    rng = np.random.default_rng(11)
    f1s = []
    for _ in range(N_BOOT):
        idx = rng.integers(0, len(y), len(y))
        f1s.append(f1_score(y[idx], pred[idx], labels=MECH, average="macro",
                            zero_division=0))
    out["macro_f1_ci95"] = [float(np.percentile(f1s, 2.5)), float(np.percentile(f1s, 97.5))]
    return out


def cv_variant(train, features, text, api, clf, task):
    x = as_inputs(train)
    y = np.array([(r["mechanism"] != "retain") if task == "binary" else r["mechanism"]
                  for r in train])
    groups = np.array([r["repo_key"] for r in train])
    skf = StratifiedGroupKFold(n_splits=5, shuffle=True, random_state=SEED)
    oof = np.zeros((len(y), 2 if task == "binary" else len(MECH)))
    model = make_model(features, text, api, clf)
    for tr, te in skf.split(x, y, groups):
        model = make_model(features, text, api, clf)
        model.fit([x[i] for i in tr], y[tr])
        proba = model.predict_proba([x[i] for i in te])
        classes = list(model.classes_)
        if task == "binary":
            oof[te] = proba[:, [list(classes).index(False) if False in classes else 0,
                                list(classes).index(True) if True in classes else -1]]
        else:
            for col, cls in enumerate(classes):
                oof[te, MECH.index(cls)] = proba[:, col]
    if task == "binary":
        return binary_metrics(train, oof[:, 1])
    return multi_metrics(train, oof, MECH)


def main():
    train, valid = load()
    results = {"dataset": DATASET.name,
               "sizes": {"train": len(train), "valid": len(valid)},
               "variants": {}}
    configs = {
        "feat_lr": dict(features=True, text=False, clf="lr"),
        "feat_api_lr": dict(features=True, text=False, api=True, clf="lr"),
        "feat_text_lr": dict(features=True, text=True, clf="lr"),
        "feat_api_text_lr": dict(features=True, text=True, api=True, clf="lr"),
        "feat_gb": dict(features=True, text=False, api=False, clf="gb"),
        "text_api_lr": dict(features=False, text=True, api=True, clf="lr"),
    }
    for name, cfg in configs.items():
        model = make_model(cfg["features"], cfg["text"], cfg.get("api", True), cfg["clf"])
        xtr, xva = as_inputs(train), as_inputs(valid)
        res = {}
        # binary
        ytr = np.array([r["mechanism"] != "retain" for r in train])
        model.fit(xtr, ytr)
        proba = model.predict_proba(xva)
        classes = list(model.classes_)
        pos = classes.index(True) if True in classes else 1
        res["binary"] = binary_metrics(valid, proba[:, pos])
        # multiclass
        model_m = make_model(cfg["features"], cfg["text"], cfg.get("api", True), cfg["clf"])
        model_m.fit(xtr, [r["mechanism"] for r in train])
        proba_m = model_m.predict_proba(xva)
        classes_m = list(model_m.classes_)
        full = np.zeros((len(valid), len(MECH)))
        for col, cls in enumerate(classes_m):
            full[:, MECH.index(cls)] = proba_m[:, col]
        res["multi"] = multi_metrics(valid, full, MECH)
        results["variants"][name] = res
        print(f"{name:20s} binary AUC={res['binary']['roc_auc']:.3f} "
              f"acc={res['binary']['accuracy']:.3f} | multi acc={res['multi']['accuracy']:.3f} "
              f"macroF1={res['multi']['macro_f1']:.3f}")

    # CV for the two most interesting variants
    for name, cfg in (("feat_lr", configs["feat_lr"]),
                      ("feat_api_text_lr", configs["feat_api_text_lr"])):
        results["variants"][name]["cv_binary"] = cv_variant(
            train, cfg["features"], cfg["text"], cfg.get("api", True), cfg["clf"], "binary")
        results["variants"][name]["cv_multi"] = cv_variant(
            train, cfg["features"], cfg["text"], cfg.get("api", True), cfg["clf"], "multi")

    json.dump(results, open(OUT / "baseline_features_v0.5.json", "w"),
              indent=2, ensure_ascii=False)

    md = ["# Feature-based classification of unsafe usage (v0.5)", "",
          "Binary target: does a safe remediation exist (retain vs mechanism)?",
          "Multiclass: which remediation class. Fit on train; frozen valid scored once.", "",
          "| variant | binary AUC | binary acc | AP | multi acc | multi macro-F1 |",
          "|---|---:|---:|---:|---:|---:|"]
    for name, r in results["variants"].items():
        b, m = r["binary"], r["multi"]
        md.append(f"| {name} | {b['roc_auc']:.3f} | {b['accuracy']:.3f} | "
                  f"{b['average_precision']:.3f} | {m['accuracy']:.3f} | {m['macro_f1']:.3f} |")
    md += ["", "Bootstrap 95% CI on valid (binary AUC / accuracy):", ""]
    for name, r in results["variants"].items():
        ci = r["binary"]["ci95"]
        md.append(f"- {name}: AUC {ci['roc_auc'][0]:.3f}-{ci['roc_auc'][1]:.3f}, "
                  f"accuracy {ci['accuracy'][0]:.3f}-{ci['accuracy'][1]:.3f}")
    if "cv_binary" in results["variants"]["feat_lr"]:
        md += ["", "Grouped CV (train):", ""]
        for name in ("feat_lr", "feat_api_text_lr"):
            r = results["variants"][name]
            md.append(f"- {name}: binary CV AUC {r['cv_binary']['roc_auc']:.3f}, "
                      f"acc {r['cv_binary']['accuracy']:.3f}; "
                      f"multi CV macro-F1 {r['cv_multi']['macro_f1']:.3f}")
    (OUT / "baseline_features_v0.5.md").write_text("\n".join(md) + "\n")
    print(f"\nwrote {OUT}/baseline_features_v0.5.json and .md")


if __name__ == "__main__":
    main()
