"""Classification view of unsafe-usage remediation (v0.5 data).

The deliverable is a classifier, not a generator: given an unsafe snippet
(+ the unsafe API it uses), assign it to one remediation class:

    retain, checked_api, slice_view, init_memory, capacity_ops, safe_wrapper,
    interior_mutability, pin_api, restructure, unnecessary, other

`retain` is a genuine class ("no safe replacement in this frame"), not an
abstention wrapper. The same model therefore answers both questions:

  binary   - is a safe remediation available at all (retain vs the rest)?
  multi    - which remediation class applies?

Reported with classification metrics, not ranking metrics: accuracy, macro and
weighted F1, per-class precision/recall/F1/support, confusion matrix, and
bootstrap intervals on the frozen valid split. Baselines: majority, api lookup,
char TF-IDF, TF-IDF + API, and a hierarchical family->mechanism classifier.

Writes out/baseline_classification_v0.5.{json,md}.
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
from sklearn.pipeline import FeatureUnion, Pipeline
from sklearn.preprocessing import OneHotEncoder

from baseline_mechanism import MECH, SelectField, text_api
from mechanism_taxonomy import FAMILIES

OUT = Path(__file__).resolve().parent / "out"
DATASET = OUT / "mechanism_dataset_v05.jsonl"
FAMILIES_ALL = ["retain"] + list(FAMILIES)   # retain + 5 families + 'other' family
SEED = 0
N_BOOT = 2000


def load():
    rows = [json.loads(x) for x in DATASET.open() if x.strip()]
    train = [r for r in rows if r["split"] == "train"]
    valid = [r for r in rows if r["split"] == "valid"]
    test = [r for r in rows if r["split"] == "test"]
    assert (len(valid), len(test)) == (87, 130), "valid/test must stay frozen"
    for r in rows:
        r["family_label"] = "retain" if r["mechanism"] == "retain" else r["family"]
    return train, valid, test


def char_pipeline():
    return Pipeline([
        ("tfidf", TfidfVectorizer(analyzer="char_wb", ngram_range=(2, 5),
                                  sublinear_tf=True, min_df=2)),
        ("clf", LogisticRegression(class_weight="balanced", max_iter=3000,
                                   C=1.0, random_state=SEED)),
    ])


def char_api_pipeline():
    return Pipeline([
        ("feat", FeatureUnion([
            ("tfidf", Pipeline([
                ("sel", SelectField("text")),
                ("tfidf", TfidfVectorizer(analyzer="char_wb", ngram_range=(2, 5),
                                          sublinear_tf=True, min_df=2)),
            ])),
            ("api", Pipeline([
                ("sel", SelectField("api")),
                ("oh", OneHotEncoder(handle_unknown="ignore")),
            ])),
        ])),
        ("clf", LogisticRegression(class_weight="balanced", max_iter=3000,
                                   C=1.0, random_state=SEED)),
    ])


class ApiLookup:
    def __init__(self, classes, default):
        self.classes, self.default = classes, default

    def fit(self, x, y):
        by_api: dict[str, Counter] = {}
        for (api,), cls in zip(x, y):
            by_api.setdefault(api, Counter())[cls] += 1
        self.map = {a: c.most_common(1)[0][0] for a, c in by_api.items()}
        return self

    def predict(self, x):
        return [self.map.get(api[0], self.default) for api in x]


class ConstantMech:
    def __init__(self, mech):
        self.mech = mech

    def predict(self, texts):
        return [self.mech] * len(texts)


class Hierarchical:
    """Family (retain + 5) first, then a mechanism model per family."""

    def __init__(self, train_rows, families):
        self.families = families
        self.family_model = char_api_pipeline()
        self.mech_models = {}
        for fam in families:
            if fam == "retain":
                continue
            subset = [r for r in train_rows if r["family_label"] == fam]
            mechs = {r["mechanism"] for r in subset}
            if not mechs:
                continue
            if len(mechs) == 1:
                self.mech_models[fam] = ConstantMech(next(iter(mechs)))
                continue
            m = char_pipeline()
            m.fit([r["old_snippet"] for r in subset], [r["mechanism"] for r in subset])
            self.mech_models[fam] = m

    def fit(self, rows):
        self.family_model.fit(text_api(rows), [r["family_label"] for r in rows])
        return self

    def predict(self, rows):
        fam = self.family_model.predict(text_api(rows))
        fam_proba = self.family_model.predict_proba(text_api(rows))
        out = []
        for i, f in enumerate(fam):
            if f == "retain" or f not in self.mech_models:
                # fall back to the family model's own argmax if no mechanism model
                out.append("retain" if f == "retain" else f)
                continue
            m = self.mech_models[f]
            mech = m.predict([rows[i]["old_snippet"]])[0]
            out.append(mech)
        return out, fam


def classification_metrics(rows, pred, labels=None, boot=True):
    y = np.array([r["mechanism"] for r in rows])
    pred = np.array(pred)
    labels = labels or MECH
    out = {
        "n": len(y),
        "accuracy": float(accuracy_score(y, pred)),
        "macro_f1": float(f1_score(y, pred, labels=labels, average="macro",
                                   zero_division=0)),
        "weighted_f1": float(f1_score(y, pred, labels=labels, average="weighted",
                                      zero_division=0)),
    }
    p, r, f, s = precision_recall_fscore_support(y, pred, labels=labels,
                                                 zero_division=0)
    out["per_class"] = {
        lab: {"precision": float(p[i]), "recall": float(r[i]),
              "f1": float(f[i]), "support": int(s[i])}
        for i, lab in enumerate(labels)
        if s[i] or p[i] or r[i]
    }
    cm = confusion_matrix(y, pred, labels=labels)
    pairs = sorted(((labels[i], labels[j], int(cm[i, j]))
                    for i in range(len(labels)) for j in range(len(labels))
                    if i != j and cm[i, j]),
                   key=lambda t: -t[2])[:10]
    out["top_confusions"] = [{"true": a, "pred": b, "n": n} for a, b, n in pairs]
    if boot:
        rng = np.random.default_rng(1234)
        accs, f1s = [], []
        for _ in range(N_BOOT):
            idx = rng.integers(0, len(y), len(y))
            yy, pp = y[idx], pred[idx]
            accs.append(accuracy_score(yy, pp))
            f1s.append(f1_score(yy, pp, labels=labels, average="macro",
                                zero_division=0))
        out["ci95"] = {
            "accuracy": [float(np.percentile(accs, 2.5)), float(np.percentile(accs, 97.5))],
            "macro_f1": [float(np.percentile(f1s, 2.5)), float(np.percentile(f1s, 97.5))],
        }
    return out


FAM_LABELS = ["retain"] + list(FAMILIES)


def family_metrics(rows, pred):
    """Collapse mechanisms to families (6 classes including retain)."""
    from mechanism_taxonomy import family as fam_of
    y = np.array(["retain" if r["mechanism"] == "retain" else r["family_label"]
                  for r in rows])
    p = np.array(["retain" if x == "retain" else fam_of(x) for x in pred])
    out = {
        "accuracy": float(accuracy_score(y, p)),
        "macro_f1": float(f1_score(y, p, labels=FAM_LABELS, average="macro",
                                  zero_division=0)),
        "weighted_f1": float(f1_score(y, p, labels=FAM_LABELS, average="weighted",
                                      zero_division=0)),
    }
    rng = np.random.default_rng(5)
    accs = []
    for _ in range(N_BOOT):
        idx = rng.integers(0, len(y), len(y))
        accs.append(accuracy_score(y[idx], p[idx]))
    out["accuracy_ci95"] = [float(np.percentile(accs, 2.5)),
                            float(np.percentile(accs, 97.5))]
    prec, rec, f1, sup = precision_recall_fscore_support(y, p, labels=FAM_LABELS,
                                                         zero_division=0)
    out["per_class"] = {lab: {"precision": float(prec[i]), "recall": float(rec[i]),
                              "f1": float(f1[i]), "support": int(sup[i])}
                        for i, lab in enumerate(FAM_LABELS)}
    return out


def binary_metrics(rows, pred):
    y = np.array([r["mechanism"] != "retain" for r in rows])
    pred = np.array([p != "retain" for p in pred])
    p, r, f, s = precision_recall_fscore_support(
        y, pred, labels=[False, True], zero_division=0)
    rng = np.random.default_rng(99)
    accs = []
    for _ in range(N_BOOT):
        idx = rng.integers(0, len(y), len(y))
        accs.append(accuracy_score(y[idx], pred[idx]))
    return {
        "accuracy": float(accuracy_score(y, pred)),
        "accuracy_ci95": [float(np.percentile(accs, 2.5)),
                          float(np.percentile(accs, 97.5))],
        "macro_f1": float(f1_score(y, pred, average="macro", zero_division=0)),
        "per_class": {
            "retain": {"precision": float(p[0]), "recall": float(r[0]), "f1": float(f[0]), "support": int(s[0])},
            "mechanism": {"precision": float(p[1]), "recall": float(r[1]), "f1": float(f[1]), "support": int(s[1])},
        },
    }


def main():
    train, valid, test = load()
    results = {
        "dataset": DATASET.name,
        "classes": MECH,
        "sizes": {"train": len(train), "valid": len(valid), "test_sealed": len(test),
                  "train_class_counts": dict(Counter(r["mechanism"] for r in train).most_common()),
                  "valid_class_counts": dict(Counter(r["mechanism"] for r in valid).most_common())},
        "models": {},
    }

    models = {
        "majority": DummyClassifier(strategy="most_frequent"),
        "api_lookup": ApiLookup(MECH, "retain"),
        "char_lr": char_pipeline(),
        "char_api_lr": char_api_pipeline(),
    }
    for name, model in models.items():
        if name == "majority":
            model.fit(np.zeros((len(train), 1)), [r["mechanism"] for r in train])
            pred = model.predict(np.zeros((len(valid), 1)))
        elif name == "api_lookup":
            model.fit([[r["api_guess"]] for r in train], [r["mechanism"] for r in train])
            pred = model.predict([[r["api_guess"]] for r in valid])
        elif name == "char_api_lr":
            model.fit(text_api(train), [r["mechanism"] for r in train])
            pred = model.predict(text_api(valid))
        else:
            model.fit([r["old_snippet"] for r in train], [r["mechanism"] for r in train])
            pred = model.predict([r["old_snippet"] for r in valid])
        res = {"multi": classification_metrics(valid, pred),
               "family": family_metrics(valid, pred),
               "binary": binary_metrics(valid, pred)}
        results["models"][name] = res
        print(f"{name:12s} multi acc={res['multi']['accuracy']:.3f} "
              f"macroF1={res['multi']['macro_f1']:.3f} | "
              f"binary acc={res['binary']['accuracy']:.3f}")

    hier = Hierarchical(train, FAMILIES_ALL).fit(train)
    pred_h, fam = hier.predict(valid)
    res = {"multi": classification_metrics(valid, pred_h),
           "family": family_metrics(valid, pred_h),
           "binary": binary_metrics(valid, pred_h)}
    y_fam = np.array([r["family_label"] for r in valid])
    res["family_accuracy"] = float(accuracy_score(y_fam, fam))
    res["family_macro_f1"] = float(f1_score(y_fam, fam, average="macro",
                                            zero_division=0))
    results["models"]["hierarchical"] = res
    print(f"hierarchical multi acc={res['multi']['accuracy']:.3f} "
          f"macroF1={res['multi']['macro_f1']:.3f} | family acc={res['family_accuracy']:.3f}")

    json.dump(results, open(OUT / "baseline_classification_v0.5.json", "w"),
              indent=2, ensure_ascii=False)

    md = ["# Unsafe-usage classification (v0.5 data)", "",
          "Target: the remediation class of an unsafe snippet (`retain` when no safe",
          "replacement exists in that frame). Fit on train, score the frozen valid",
          "split once; test sealed. Metrics are classification metrics.", "",
          "| model | 11-class acc | 11-class macro F1 | 6-class (family) acc | family macro F1 | binary acc |",
          "|---|---:|---:|---:|---:|---:|"]
    for name, r in results["models"].items():
        m, f, b = r["multi"], r["family"], r["binary"]
        md.append(f"| {name} | {m['accuracy']:.3f} | {m['macro_f1']:.3f} | "
                  f"{f['accuracy']:.3f} | {f['macro_f1']:.3f} | {b['accuracy']:.3f} |")
    md += ["", "Bootstrap 95% intervals on valid:", ""]
    for name, r in results["models"].items():
        ci = r["multi"]["ci95"]
        md.append(f"- {name}: accuracy {ci['accuracy'][0]:.3f}-{ci['accuracy'][1]:.3f}; "
                  f"macro F1 {ci['macro_f1'][0]:.3f}-{ci['macro_f1'][1]:.3f}")
    md += ["", "## Per-class view, family level (char_api_lr)", "",
           "| class | precision | recall | F1 | support |",
           "|---|---:|---:|---:|---:|"]
    for cls, v in results["models"]["char_api_lr"]["family"]["per_class"].items():
        md.append(f"| {cls} | {v['precision']:.3f} | {v['recall']:.3f} | "
                  f"{v['f1']:.3f} | {v['support']} |")
    md += ["", "## Per-class view, mechanism level (char_api_lr)", "",
           "| class | precision | recall | F1 | support |",
           "|---|---:|---:|---:|---:|"]
    for cls, v in results["models"]["char_api_lr"]["multi"]["per_class"].items():
        md.append(f"| {cls} | {v['precision']:.3f} | {v['recall']:.3f} | "
                  f"{v['f1']:.3f} | {v['support']} |")
    md += ["", "Most frequent confusions (true -> predicted):", ""]
    for c in results["models"]["char_api_lr"]["multi"]["top_confusions"]:
        md.append(f"- {c['true']} -> {c['pred']}: {c['n']}")
    md += ["", "## Binary collapse (retain vs any mechanism)", ""]
    for name, r in results["models"].items():
        b = r["binary"]
        md.append(f"- {name}: accuracy {b['accuracy']:.3f} "
                  f"({b['accuracy_ci95'][0]:.3f}-{b['accuracy_ci95'][1]:.3f}), "
                  f"retain F1 {b['per_class']['retain']['f1']:.3f}, "
                  f"mechanism F1 {b['per_class']['mechanism']['f1']:.3f}")
    (OUT / "baseline_classification_v0.5.md").write_text("\n".join(md) + "\n")
    print(f"\nwrote {OUT}/baseline_classification_v0.5.json and .md")


if __name__ == "__main__":
    main()
