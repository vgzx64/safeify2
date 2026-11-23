"""Hazard-classification baseline on the v0.5 corpus.

Primary task: predict the site's hazard class from `old_snippet` (+ api) among
the ten locally determinable hazards. Rows whose unsafe operation is only a
delegated call (`unsafe_call`) or undeterminable (`unknown`) are excluded from
this task and reported as coverage, because their hazard is not visible in the
input.

Secondary: the full 12-class problem, for completeness.

Labels are rule-derived (`hazard_taxonomy.classify`); the blind audit
(`score_hazard_agreement.py`) measures whether annotators agree with the
taxonomy. A classifier trained on rule labels measures how much of the hazard
is recoverable from text rather than by the exact rule that fired.

Writes out/baseline_hazard_v0.1.{json,md}.
"""

from __future__ import annotations

import json
from collections import Counter
from pathlib import Path

import numpy as np
from sklearn.dummy import DummyClassifier
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import (accuracy_score, confusion_matrix, f1_score,
                             precision_recall_fscore_support)
from sklearn.model_selection import StratifiedGroupKFold
from sklearn.pipeline import FeatureUnion, Pipeline
from sklearn.preprocessing import OneHotEncoder

OUT = Path(__file__).resolve().parent / "out"
DETERMINABLE = ["raw_ownership", "manual_capacity", "raw_memory", "uninit_memory",
                "reinterpret", "raw_deref", "unchecked_index", "ffi_boundary",
                "unsafe_trait", "unsafe_contract"]
ALL_CLASSES = DETERMINABLE + ["unsafe_call", "unknown"]
SEED = 0
N_BOOT = 2000


class SelectText:
    def fit(self, x, y=None):
        return self

    def transform(self, x):
        return [r["old_snippet"] for r in x]


class SelectApi:
    def fit(self, x, y=None):
        return self

    def transform(self, x):
        return [[r.get("api_guess") or "unknown"] for r in x]


def model():
    return Pipeline([
        ("feat", FeatureUnion([
            ("tfidf", Pipeline([
                ("sel", SelectText()),
                ("tfidf", TfidfVectorizer(analyzer="char_wb", ngram_range=(2, 5),
                                          sublinear_tf=True, min_df=2)),
            ])),
            ("api", Pipeline([
                ("sel", SelectApi()),
                ("oh", OneHotEncoder(handle_unknown="ignore")),
            ])),
        ])),
        ("clf", LogisticRegression(class_weight="balanced", max_iter=3000,
                                   C=1.0, random_state=SEED)),
    ])


def load():
    rows = [json.loads(x) for x in (OUT / "mechanism_dataset_v05.jsonl").open() if x.strip()]
    hazards = {r["id"]: r for r in
               (json.loads(x) for x in (OUT / "hazard_labels.jsonl").open() if x.strip())}
    for r in rows:
        r["hazard"] = hazards[r["id"]]["hazard"]
    train = [r for r in rows if r["split"] == "train"]
    valid = [r for r in rows if r["split"] == "valid"]
    test = [r for r in rows if r["split"] == "test"]
    assert (len(valid), len(test)) == (87, 130)
    return train, valid


def metrics(rows, pred, classes):
    y = np.array([r["hazard"] for r in rows])
    pred = np.array(pred)
    out = {"n": len(y),
           "accuracy": float(accuracy_score(y, pred)),
           "macro_f1": float(f1_score(y, pred, labels=classes, average="macro",
                                      zero_division=0)),
           "weighted_f1": float(f1_score(y, pred, labels=classes, average="weighted",
                                         zero_division=0))}
    p, r, f, s = precision_recall_fscore_support(y, pred, labels=classes, zero_division=0)
    out["per_class"] = {c: {"precision": float(p[i]), "recall": float(r[i]),
                            "f1": float(f[i]), "support": int(s[i])}
                        for i, c in enumerate(classes)}
    cm = confusion_matrix(y, pred, labels=classes)
    pairs = sorted(((classes[i], classes[j], int(cm[i, j]))
                    for i in range(len(classes)) for j in range(len(classes))
                    if i != j and cm[i, j]), key=lambda t: -t[2])[:8]
    out["top_confusions"] = [{"true": a, "pred": b, "n": n} for a, b, n in pairs]
    rng = np.random.default_rng(3)
    accs, f1s = [], []
    for _ in range(N_BOOT):
        idx = rng.integers(0, len(y), len(y))
        accs.append(accuracy_score(y[idx], pred[idx]))
        f1s.append(f1_score(y[idx], pred[idx], labels=classes, average="macro",
                            zero_division=0))
    out["ci95"] = {"accuracy": [float(np.percentile(accs, 2.5)),
                                float(np.percentile(accs, 97.5))],
                   "macro_f1": [float(np.percentile(f1s, 2.5)),
                                float(np.percentile(f1s, 97.5))]}
    return out


def cv(rows, classes):
    x = [{"old_snippet": r["old_snippet"], "api_guess": r.get("api_guess")} for r in rows]
    y = np.array([r["hazard"] for r in rows])
    groups = np.array([r["repo_key"] for r in rows])
    skf = StratifiedGroupKFold(n_splits=5, shuffle=True, random_state=SEED)
    oof = np.zeros((len(y), len(classes)))
    for tr, te in skf.split(x, y, groups):
        m = model()
        m.fit([x[i] for i in tr], y[tr])
        proba = m.predict_proba([x[i] for i in te])
        for col, cls in enumerate(m.classes_):
            oof[te, classes.index(cls)] = proba[:, col]
    pred = [classes[int(j)] for j in oof.argmax(axis=1)]
    return metrics(rows, pred, classes)


def run(train, valid, classes, tag):
    tr = [r for r in train if r["hazard"] in classes]
    va = [r for r in valid if r["hazard"] in classes]
    x_tr = [{"old_snippet": r["old_snippet"], "api_guess": r.get("api_guess")} for r in tr]
    x_va = [{"old_snippet": r["old_snippet"], "api_guess": r.get("api_guess")} for r in va]
    m = model()
    m.fit(x_tr, [r["hazard"] for r in tr])
    proba = m.predict_proba(x_va)
    full = np.zeros((len(va), len(classes)))
    for col, cls in enumerate(m.classes_):
        full[:, classes.index(cls)] = proba[:, col]
    pred = [classes[int(j)] for j in full.argmax(axis=1)]
    return {"train_rows": len(tr), "valid_rows": len(va),
            "valid": metrics(va, pred, classes),
            "cv": cv(tr, classes)}


def main():
    train, valid = load()
    results = {"dataset": "out/mechanism_dataset_v05.jsonl",
               "hazard_labels": "out/hazard_labels.jsonl",
               "class_support": {
                   "train": dict(Counter(r["hazard"] for r in train).most_common()),
                   "valid": dict(Counter(r["hazard"] for r in valid).most_common())},
               "coverage": {
                   "train_determinable": sum(1 for r in train if r["hazard"] in DETERMINABLE) / len(train),
                   "valid_determinable": sum(1 for r in valid if r["hazard"] in DETERMINABLE) / len(valid),
               }}

    results["ten_class"] = run(train, valid, DETERMINABLE, "ten")
    print(f"ten-class: train {results['ten_class']['train_rows']}, "
          f"valid {results['ten_class']['valid_rows']}, "
          f"acc {results['ten_class']['valid']['accuracy']:.3f}, "
          f"macroF1 {results['ten_class']['valid']['macro_f1']:.3f}")

    results["twelve_class"] = run(train, valid, ALL_CLASSES, "twelve")
    print(f"twelve-class: acc {results['twelve_class']['valid']['accuracy']:.3f}, "
          f"macroF1 {results['twelve_class']['valid']['macro_f1']:.3f}")

    # majority reference on the same valid subset
    va = [r for r in valid if r["hazard"] in DETERMINABLE]
    majority = Counter(r["hazard"] for r in train if r["hazard"] in DETERMINABLE).most_common(1)[0][0]
    results["majority_reference"] = {
        "class": majority,
        "valid": metrics(va, [majority] * len(va), DETERMINABLE)}

    json.dump(results, open(OUT / "baseline_hazard_v0.1.json", "w"),
              indent=2, ensure_ascii=False)

    md = ["# Hazard classification (v0.5 labels, rule-derived)", "",
          "Predict the site's hazard class from `old_snippet` + `api_guess`. Rows whose",
          "unsafe operation is only a delegated call (`unsafe_call`) or undeterminable",
          "(`unknown`) are excluded from the primary task and reported as coverage.",
          "Fit on train, score the frozen valid split once; test sealed.", "",
          "| task | train rows | valid rows | accuracy | macro F1 |",
          "|---|---:|---:|---:|---:|"]
    t, w = results["ten_class"], results["twelve_class"]
    md.append(f"| 10 hazards | {t['train_rows']} | {t['valid_rows']} | "
              f"{t['valid']['accuracy']:.3f} | {t['valid']['macro_f1']:.3f} |")
    md.append(f"| 12 classes | {w['train_rows']} | {w['valid_rows']} | "
              f"{w['valid']['accuracy']:.3f} | {w['valid']['macro_f1']:.3f} |")
    md += ["", f"Coverage of determinable hazards: train "
           f"{results['coverage']['train_determinable']:.3f}, valid "
           f"{results['coverage']['valid_determinable']:.3f}.", "",
           "## Per-class, 10-hazard task", "",
           "| hazard | precision | recall | F1 | support |", "|---|---:|---:|---:|---:|"]
    for c, v in results["ten_class"]["valid"]["per_class"].items():
        md.append(f"| {c} | {v['precision']:.3f} | {v['recall']:.3f} | {v['f1']:.3f} | {v['support']} |")
    md += ["", "Top confusions:", ""]
    for c in results["ten_class"]["valid"]["top_confusions"]:
        md.append(f"- {c['true']} -> {c['pred']}: {c['n']}")
    md += ["", "Bootstrap 95% CI (10-hazard): accuracy "
           f"{t['valid']['ci95']['accuracy'][0]:.3f}-{t['valid']['ci95']['accuracy'][1]:.3f}, "
           f"macro F1 {t['valid']['ci95']['macro_f1'][0]:.3f}-{t['valid']['ci95']['macro_f1'][1]:.3f}.", "",
           f"Grouped CV (train): accuracy {t['cv']['accuracy']:.3f}, macro F1 {t['cv']['macro_f1']:.3f}."]
    (OUT / "baseline_hazard_v0.1.md").write_text("\n".join(md) + "\n")
    print(f"\nwrote {OUT}/baseline_hazard_v0.1.json and .md")


if __name__ == "__main__":
    main()
