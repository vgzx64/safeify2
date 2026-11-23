"""Human-supervised hazard classifier: does annotating the train set help?

Trains on the 300 blind human hazard labels (adjudication/hazard_train) and
evaluates on the 87 human valid labels (adjudication/hazard_valid). The
rule-labelled baseline is retrained here for comparison on the same valid rows.

Writes out/hazard_human_train_v0.1.{json,md}.
"""

from __future__ import annotations

import json
from collections import Counter
from pathlib import Path

import numpy as np
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import (accuracy_score, confusion_matrix, f1_score,
                             precision_recall_fscore_support)
from sklearn.model_selection import StratifiedGroupKFold
from sklearn.pipeline import FeatureUnion, Pipeline
from sklearn.preprocessing import OneHotEncoder

from hazard_taxonomy import HAZARDS

HERE = Path(__file__).resolve().parent
OUT = HERE / "out"
TRAIN_LABELS = HERE / "adjudication/hazard_train"
VALID_LABELS = HERE / "adjudication/hazard_valid"
DETERMINABLE = ["raw_ownership", "manual_capacity", "raw_memory", "uninit_memory",
                "reinterpret", "raw_deref", "unchecked_index", "ffi_boundary",
                "unsafe_trait", "unsafe_contract"]
ALL = DETERMINABLE + ["unsafe_call", "unknown"]


class SelText:
    def fit(self, x, y=None):
        return self

    def transform(self, x):
        return [r["old_snippet"] for r in x]


class SelApi:
    def fit(self, x, y=None):
        return self

    def transform(self, x):
        return [[r.get("api_guess") or "unknown"] for r in x]


def model():
    return Pipeline([
        ("feat", FeatureUnion([
            ("tfidf", Pipeline([("sel", SelText()),
                                ("tfidf", TfidfVectorizer(analyzer="char_wb",
                                                          ngram_range=(2, 5),
                                                          sublinear_tf=True, min_df=2))])),
            ("api", Pipeline([("sel", SelApi()),
                              ("oh", OneHotEncoder(handle_unknown="ignore"))])),
        ])),
        ("clf", LogisticRegression(class_weight="balanced", max_iter=3000, C=1.0,
                                   random_state=0)),
    ])


def read_labels(directory: Path) -> dict[str, str]:
    out = {}
    for path in sorted(directory.glob("labels_batch_*.jsonl")):
        for r in (json.loads(x) for x in path.open() if x.strip()):
            out[r["id"]] = r["hazard"]
    return out


def metrics(rows, pred, classes):
    y = np.array([r["hazard"] for r in rows])
    pred = np.array(pred)
    p, r, f, s = precision_recall_fscore_support(y, pred, labels=classes, zero_division=0)
    cm = confusion_matrix(y, pred, labels=classes)
    pairs = sorted(((classes[i], classes[j], int(cm[i, j]))
                    for i in range(len(classes)) for j in range(len(classes))
                    if i != j and cm[i, j]), key=lambda t: -t[2])[:10]
    rng = np.random.default_rng(3)
    accs, f1s = [], []
    for _ in range(2000):
        idx = rng.integers(0, len(y), len(y))
        accs.append(accuracy_score(y[idx], pred[idx]))
        f1s.append(f1_score(y[idx], pred[idx], labels=classes, average="macro",
                            zero_division=0))
    return {"n": len(y), "accuracy": float(accuracy_score(y, pred)),
            "macro_f1": float(f1_score(y, pred, labels=classes, average="macro",
                                       zero_division=0)),
            "per_class": {c: {"precision": float(p[i]), "recall": float(r[i]),
                              "f1": float(f[i]), "support": int(s[i])}
                          for i, c in enumerate(classes)},
            "top_confusions": [{"true": a, "pred": b, "n": n} for a, b, n in pairs],
            "ci95": {"accuracy": [float(np.percentile(accs, 2.5)),
                                  float(np.percentile(accs, 97.5))],
                     "macro_f1": [float(np.percentile(f1s, 2.5)),
                                  float(np.percentile(f1s, 97.5))]}}


def fit_eval(train_rows, train_labels, valid_rows, valid_labels, classes):
    tr = [r for r in train_rows if train_labels.get(r["id"]) in classes]
    va = [r for r in valid_rows if valid_labels.get(r["id"]) in classes]
    x_tr = [{"old_snippet": r["old_snippet"], "api_guess": r.get("api_guess")} for r in tr]
    x_va = [{"old_snippet": r["old_snippet"], "api_guess": r.get("api_guess")} for r in va]
    m = model()
    m.fit(x_tr, [train_labels[r["id"]] for r in tr])
    proba = m.predict_proba(x_va)
    cls = list(m.classes_)
    pred = [cls[int(j)] for j in proba.argmax(axis=1)]
    human_rows = [{"hazard": valid_labels[r["id"]]} for r in va]
    out = {"train_rows": len(tr), "valid_rows": len(va),
           "valid": metrics(human_rows, pred, classes)}
    # grouped CV on the training labels for stability
    y = np.array([train_labels[r["id"]] for r in tr])
    groups = np.array([r["repo_key"] for r in tr])
    skf = StratifiedGroupKFold(n_splits=5, shuffle=True, random_state=0)
    oof = np.zeros((len(y), len(classes)))
    for a, b in skf.split(x_tr, y, groups):
        mm = model()
        mm.fit([x_tr[i] for i in a], y[a])
        pp = mm.predict_proba([x_tr[i] for i in b])
        for col, c in enumerate(mm.classes_):
            oof[b, classes.index(c)] = pp[:, col]
    cv_pred = [classes[int(j)] for j in oof.argmax(axis=1)]
    out["cv"] = {"n": len(y),
                 "accuracy": float(accuracy_score(y, cv_pred)),
                 "macro_f1": float(f1_score(y, cv_pred, labels=classes,
                                            average="macro", zero_division=0))}
    return out


def main() -> int:
    rows = [json.loads(x) for x in (OUT / "mechanism_dataset_v05.jsonl").open() if x.strip()]
    rules = {r["id"]: r["hazard"] for r in
             (json.loads(x) for x in (OUT / "hazard_labels.jsonl").open() if x.strip())}
    human_train = read_labels(TRAIN_LABELS)
    human_valid = read_labels(VALID_LABELS)
    train = [r for r in rows if r["split"] == "train"]
    valid = [r for r in rows if r["split"] == "valid"]
    report = {
        "human_train_labels": len(human_train),
        "human_valid_labels": len(human_valid),
        "human_train_distribution": dict(Counter(human_train.values()).most_common()),
        "valid_distribution": dict(Counter(human_valid.values()).most_common()),
        "models": {},
    }
    report["models"]["rule_trained_10"] = fit_eval(train, rules, valid, human_valid,
                                                   DETERMINABLE)
    report["models"]["human_trained_10"] = fit_eval(train, human_train, valid, human_valid,
                                                    DETERMINABLE)
    report["models"]["human_trained_12"] = fit_eval(train, human_train, valid, human_valid,
                                                    ALL)
    report["rule_vs_human_valid"] = {
        "agreement": float(np.mean([rules[r["id"]] == human_valid[r["id"]]
                                    for r in valid if r["id"] in human_valid]))}

    json.dump(report, open(OUT / "hazard_human_train_v0.1.json", "w"),
              indent=2, ensure_ascii=False)
    md = ["# Hazard classifier — human-supervised run", "",
          f"Train labels: {len(human_train)} blind human hazard labels. Valid: "
          f"{len(human_valid)} human labels. Both models are scored on the same",
          "human valid labels; test stays sealed.", "",
          "| training labels | task | train rows | valid rows | accuracy | macro F1 |",
          "|---|---|---:|---:|---:|---:|"]
    for name, r in report["models"].items():
        classes = {"rule_trained_10": "10", "human_trained_10": "10",
                   "human_trained_12": "12"}[name]
        md.append(f"| {name} | {classes} classes | {r['train_rows']} | {r['valid_rows']} | "
                  f"{r['valid']['accuracy']:.3f} | {r['valid']['macro_f1']:.3f} |")
    md += ["", f"Rules vs human valid labels: {report['rule_vs_human_valid']['agreement']:.3f}.", "",
           "Grouped CV on the training labels (human labels, 10-class): "
           f"accuracy {report['models']['human_trained_10']['cv']['accuracy']:.3f}, "
           f"macro F1 {report['models']['human_trained_10']['cv']['macro_f1']:.3f}.", "",
           "## Per class (human-trained, 10-class, vs human valid)", "",
           "| hazard | precision | recall | F1 | support |", "|---|---:|---:|---:|---:|"]
    for c, v in report["models"]["human_trained_10"]["valid"]["per_class"].items():
        md.append(f"| {c} | {v['precision']:.3f} | {v['recall']:.3f} | {v['f1']:.3f} | {v['support']} |")
    md += ["", "Top confusions:", ""]
    for c in report["models"]["human_trained_10"]["valid"]["top_confusions"]:
        md.append(f"- {c['true']} -> {c['pred']}: {c['n']}")
    (OUT / "hazard_human_train_v0.1.md").write_text("\n".join(md) + "\n")
    print(json.dumps({k: {"train": v["train_rows"], "valid": v["valid_rows"],
                          "acc": v["valid"]["accuracy"], "mf1": v["valid"]["macro_f1"]}
                      for k, v in report["models"].items()}, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
