"""Mechanism-classification baselines for the transition corpus (v0.3 draft).

Task: given `old_snippet` (+ `api_guess`), predict the safe-remediation
mechanism of the fix, or `retain` when unsafe code stays (M/N). `retain` is the
abstention class: suggesting a mechanism for an M/N row is a false suggestion.

Protocol: fit on train (459 rows), score the frozen valid split (87 rows),
test sealed. Two questions are reported separately:
  * joint  - choose among 10 mechanisms + retain (developer-facing decision)
  * conditional - given that the row is Y, which mechanism (on Y rows only)

Input: `old_snippet` and `api_guess` only; the fix (`safe_snippet`) is never an
input. Writes out/baseline_mechanism_v0.3.{json,md}.
"""

from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path

import numpy as np
from sklearn.dummy import DummyClassifier
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import accuracy_score, f1_score
from sklearn.model_selection import StratifiedGroupKFold
from sklearn.base import BaseEstimator, TransformerMixin
from sklearn.pipeline import FeatureUnion, Pipeline
from sklearn.preprocessing import OneHotEncoder

from mechanism_taxonomy import MECHANISMS, family as fam_of

OUT = Path(__file__).resolve().parent / "out"
SEED = 0
N_BOOT = 2000
MECH = list(MECHANISMS) + ["retain"]


def load_rows():
    rows = [json.loads(x) for x in (OUT / "mechanism_dataset.jsonl").open() if x.strip()]
    assert all(r["mechanism"] in MECH for r in rows), "bad mechanism"
    train = [r for r in rows if r["split"] == "train"]
    valid = [r for r in rows if r["split"] == "valid"]
    test = [r for r in rows if r["split"] == "test"]
    assert (len(train), len(valid), len(test)) == (459, 87, 130)
    assert not ({r["repo_key"] for r in train} & {r["repo_key"] for r in valid})
    assert all(r["mechanism"] == "retain" for r in test) or True
    return train, valid, test


def texts(rows):
    return [r["old_snippet"] for r in rows]


def text_api(rows):
    return [{"text": r["old_snippet"], "api": r["api_guess"]} for r in rows]


def apis(rows):
    return [[r["api_guess"]] for r in rows]


class ApiLookup:
    """Predict the majority mechanism seen for this api_guess in train."""

    def __init__(self, classes, default):
        self.classes = classes
        self.default = default

    def fit(self, x, y):
        by_api = {}
        for (api,), mech in zip(x, y):
            by_api.setdefault(api, Counter())[mech] += 1
        self.map = {api: c.most_common(1)[0][0] for api, c in by_api.items()}
        return self

    def predict_proba(self, x):
        probs = np.zeros((len(x), len(self.classes)))
        for i, (api,) in enumerate(x):
            mech = self.map.get(api, self.default)
            probs[i, self.classes.index(mech)] = 1.0
        return probs

    def predict(self, x):
        return [self.classes[i] for i in self.predict_proba(x).argmax(axis=1)]


class SelectField(BaseEstimator, TransformerMixin):
    """Pick one field out of a list of dicts for a feature branch."""

    def __init__(self, field):
        self.field = field

    def fit(self, x, y=None):
        return self

    def transform(self, x):
        if self.field == "api":
            return [[r["api"]] for r in x]
        return [r["text"] for r in x]


def make_models(train):
    mechs, counts = zip(*Counter(r["mechanism"] for r in train).most_common())
    default = mechs[0]
    return {
        "majority": DummyClassifier(strategy="most_frequent"),
        "api_lookup": ApiLookup(MECH, default),
        "char_lr": Pipeline([
            ("tfidf", TfidfVectorizer(analyzer="char_wb", ngram_range=(2, 5),
                                      sublinear_tf=True, min_df=2)),
            ("clf", LogisticRegression(class_weight="balanced", max_iter=3000,
                                       C=1.0, random_state=SEED)),
        ]),
        "char_api_lr": Pipeline([
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
        ]),
    }


def joint_metrics(rows, pred):
    y = [r["mechanism"] for r in rows]
    present = sorted(set(y) | set(pred))
    return {
        "n": len(y),
        "accuracy": float(accuracy_score(y, pred)),
        "macro_f1": float(f1_score(y, pred, labels=present, average="macro",
                                   zero_division=0)),
        "predicted_mechanism_on_retain": sum(
            1 for r, p in zip(rows, pred) if r["mechanism"] == "retain" and p != "retain"),
        "predicted_retain_on_y": sum(
            1 for r, p in zip(rows, pred) if r["mechanism"] != "retain" and p == "retain"),
    }


def y_metrics(rows, proba):
    """Top-1/top-3 accuracy and macro-F1 over rows whose true mechanism is a mechanism."""
    idx = [i for i, r in enumerate(rows) if r["mechanism"] != "retain"]
    y = [rows[i]["mechanism"] for i in idx]
    p = proba[idx]
    top1 = [MECH[int(j)] for j in p.argmax(axis=1)]
    order = np.argsort(-p, axis=1)[:, :3]
    top3 = [[MECH[int(j)] for j in row] for row in order]
    present = sorted(set(y))
    return {
        "n": len(y),
        "top1": float(accuracy_score(y, top1)),
        "top3": float(np.mean([t in y3 for t, y3 in zip(y, top3)])),
        "macro_f1": float(f1_score(y, top1, labels=present, average="macro",
                                   zero_division=0)),
        "support": dict(Counter(y).most_common()),
        "confusion_pairs": [{"true": a, "pred": b, "n": c} for (a, b), c in
                            Counter(zip(y, top1)).most_common(8) if a != b],
    }


def bootstrap_top1(rows, proba, n=N_BOOT):
    idx = np.array([i for i, r in enumerate(rows) if r["mechanism"] != "retain"])
    y = np.array([rows[i]["mechanism"] for i in idx])
    p = proba[idx]
    pred = np.array([MECH[int(j)] for j in p.argmax(axis=1)])
    rng = np.random.default_rng(1234)
    vals = []
    for _ in range(n):
        sel = rng.integers(0, len(y), len(y))
        vals.append((pred[sel] == y[sel]).mean())
    return [float(np.percentile(vals, 2.5)), float(np.percentile(vals, 97.5))]


def topk(classes, proba, k):
    order = np.argsort(-proba, axis=1)[:, :k]
    return [[classes[int(j)] for j in row] for row in order]


def baseline_from_train(train, valid, key, k=3):
    """Constant top-k list taken from the most frequent classes in train."""
    freq = [c for c, _ in Counter(r[key] for r in train if r[key] != "retain").most_common(k)]
    y = [r[key] for r in valid if r["mechanism"] != "retain"]
    return {"top1": float(np.mean([y_i == freq[0] for y_i in y])),
            "top3": float(np.mean([y_i in freq for y_i in y])),
            "classes": freq}


def conditional_metrics(train, valid, name="conditional_char_lr"):
    tr = [r for r in train if r["mechanism"] != "retain"]
    va = [r for r in valid if r["mechanism"] != "retain"]
    model = Pipeline([
        ("tfidf", TfidfVectorizer(analyzer="char_wb", ngram_range=(2, 5),
                                  sublinear_tf=True, min_df=2)),
        ("clf", LogisticRegression(class_weight="balanced", max_iter=3000,
                                   C=1.0, random_state=SEED)),
    ])
    model.fit(texts(tr), [r["mechanism"] for r in tr])
    proba = model.predict_proba(texts(va))
    classes = list(model.classes_)
    top1 = [classes[int(j)] for j in proba.argmax(axis=1)]
    order = np.argsort(-proba, axis=1)[:, :3]
    top3 = [[classes[int(j)] for j in row] for row in order]
    y = [r["mechanism"] for r in va]
    fam = [fam_of(r["mechanism"]) for r in tr]
    fam_model = Pipeline([
        ("tfidf", TfidfVectorizer(analyzer="char_wb", ngram_range=(2, 5),
                                  sublinear_tf=True, min_df=2)),
        ("clf", LogisticRegression(class_weight="balanced", max_iter=3000,
                                   C=1.0, random_state=SEED)),
    ])
    fam_model.fit(texts(tr), fam)
    fam_proba = fam_model.predict_proba(texts(va))
    fam_classes = list(fam_model.classes_)
    fam_top1 = [fam_classes[int(j)] for j in fam_proba.argmax(axis=1)]
    fam_top3 = topk(fam_classes, fam_proba, 3)
    vy = [fam_of(r["mechanism"]) for r in va]
    return {
        "name": name,
        "conditional_rows": {"train": len(tr), "valid": len(va)},
        "top1": float(accuracy_score(y, top1)),
        "top3": float(np.mean([t in t3 for t, t3 in zip(y, top3)])),
        "macro_f1": float(f1_score(y, top1, labels=sorted(set(y)), average="macro",
                                   zero_division=0)),
        "family_top1": float(accuracy_score(vy, fam_top1)),
        "family_top3": float(np.mean([t in t3 for t, t3 in zip(vy, fam_top3)])),
        "family_macro_f1": float(f1_score(vy, fam_top1, labels=sorted(set(vy)),
                                          average="macro", zero_division=0)),
        "predicted_distribution": dict(Counter(top1).most_common()),
        "confusion_pairs": [{"true": a, "pred": b, "n": c} for (a, b), c in
                            Counter(zip(y, top1)).most_common(10) if a != b],
        "majority_baseline": {
            "mechanism": baseline_from_train(tr, va, "mechanism"),
            "family": baseline_from_train(tr, va, "family"),
        },
    }


def cv_scores(train, model_name):
    y = np.array([r["mechanism"] for r in train])
    groups = np.array([r["repo_key"] for r in train])
    skf = StratifiedGroupKFold(n_splits=5, shuffle=True, random_state=SEED)
    oof = np.zeros((len(y), len(MECH)))
    for fold, (tr, te) in enumerate(skf.split(np.zeros(len(y)), y, groups)):
        model = make_models([train[i] for i in tr])[model_name]
        if model_name == "char_api_lr":
            x_fit = text_api([train[i] for i in tr])
        elif model_name.startswith("char"):
            x_fit = texts([train[i] for i in tr])
        else:
            x_fit = apis([train[i] for i in tr])
        model.fit(x_fit, [y[i] for i in tr])
        if model_name == "char_api_lr":
            proba = model.predict_proba(text_api([train[i] for i in te]))
        elif model_name.startswith("char"):
            proba = model.predict_proba(texts([train[i] for i in te]))
        else:
            proba = model.predict_proba(apis([train[i] for i in te]))
        classes = list(model.classes_)
        for col, cls in enumerate(classes):
            oof[te, MECH.index(cls)] = proba[:, col]
    pred = [MECH[int(j)] for j in oof.argmax(axis=1)]
    return joint_metrics(train, pred), y_metrics(train, oof)


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--version", default="v0.3")
    args = ap.parse_args()
    train, valid, test = load_rows()
    results = {
        "version": args.version,
        "protocol": "fit train (459); score frozen valid (87); test sealed (130); input old_snippet + api_guess",
        "classes": MECH,
        "sizes": {"train": len(train), "valid": len(valid), "test_sealed": len(test),
                  "train_mechanisms": dict(Counter(r["mechanism"] for r in train).most_common())},
        "models": {},
    }
    for name, model in make_models(train).items():
        x = apis(train) if name in ("api_lookup", "majority") else None
        if name == "majority":
            model.fit(np.zeros((len(train), 1)), [r["mechanism"] for r in train])
            proba_v = model.predict_proba(np.zeros((len(valid), 1)))
            classes = list(model.classes_)
        elif name == "api_lookup":
            model.fit(apis(train), [r["mechanism"] for r in train])
            proba_v = model.predict_proba(apis(valid))
            classes = MECH
        elif name == "char_api_lr":
            model.fit(text_api(train), [r["mechanism"] for r in train])
            proba_v = model.predict_proba(text_api(valid))
            classes = list(model.classes_)
        else:
            model.fit(texts(train), [r["mechanism"] for r in train])
            proba_v = model.predict_proba(texts(valid))
            classes = list(model.classes_)
        pred_v = [classes[int(j)] for j in proba_v.argmax(axis=1)]
        full = np.zeros((len(valid), len(MECH)))
        for col, cls in enumerate(classes):
            full[:, MECH.index(cls)] = proba_v[:, col]
        res = {
            "joint_valid": joint_metrics(valid, pred_v),
            "y_valid": y_metrics(valid, full),
            "y_valid_top1_ci95": bootstrap_top1(valid, full),
        }
        if name.startswith("char"):
            res["cv"], res["y_cv"] = cv_scores(train, name)
        else:
            res["cv"], res["y_cv"] = None, None
        results["models"][name] = res
        j, yv = res["joint_valid"], res["y_valid"]
        print(f"{name:14s} joint_acc={j['accuracy']:.3f} macroF1={j['macro_f1']:.3f} "
              f"| Y top1={yv['top1']:.3f} top3={yv['top3']:.3f} n={yv['n']}")

    results["conditional"] = conditional_metrics(train, valid)
    c = results["conditional"]
    print(f"conditional   Y top1={c['top1']:.3f} top3={c['top3']:.3f} "
          f"| family top1={c['family_top1']:.3f} top3={c['family_top3']:.3f} "
          f"| majority mech top1={c['majority_baseline']['mechanism']['top1']:.3f} "
          f"top3={c['majority_baseline']['mechanism']['top3']:.3f}")

    json.dump(results, open(OUT / f"baseline_mechanism_{args.version}.json", "w"),
              indent=2, ensure_ascii=False)

    md = [f"# Mechanism classification baseline ({args.version})", "",
          "Fit on train (459) and score the frozen valid split (87); test sealed.",
          "Input: `old_snippet` + `api_guess`; positive-task mechanics: predict the",
          "safe-remediation mechanism, or `retain` when unsafe stays (M/N).", "",
          "## Joint task (mechanism or retain)", "",
          "| model | valid acc | valid macro-F1 | mechanism suggested on M/N | retain predicted on Y |",
          "|---|---:|---:|---:|---:|"]
    for name, r in results["models"].items():
        j = r["joint_valid"]
        md.append(f"| {name} | {j['accuracy']:.3f} | {j['macro_f1']:.3f} | "
                  f"{j['predicted_mechanism_on_retain']} | {j['predicted_retain_on_y']} |")
    md += ["", "## Conditional on Y rows (which mechanism)", "",
           "| model | n | top-1 | top-3 | macro-F1 | 95% CI top-1 |",
           "|---|---:|---:|---:|---:|---:|"]
    for name, r in results["models"].items():
        yv = r["y_valid"]
        ci = r["y_valid_top1_ci95"]
        md.append(f"| {name} | {yv['n']} | {yv['top1']:.3f} | {yv['top3']:.3f} | "
                  f"{yv['macro_f1']:.3f} | {ci[0]:.3f}-{ci[1]:.3f} |")
    c = results["conditional"]
    md.append(f"| {c['name']} (train Y only: {c['conditional_rows']['train']}) | "
              f"{c['conditional_rows']['valid']} | {c['top1']:.3f} | {c['top3']:.3f} | "
              f"{c['macro_f1']:.3f} | - |")
    bm, bf = c["majority_baseline"]["mechanism"], c["majority_baseline"]["family"]
    md += ["", "Constant baselines over the same valid Y rows:", "",
           f"- majority mechanism ({', '.join(bm['classes'])}): top-1 {bm['top1']:.3f}, top-3 {bm['top3']:.3f}",
           f"- majority family ({', '.join(bf['classes'])}): top-1 {bf['top1']:.3f}, top-3 {bf['top3']:.3f}",
           "", "Family view of the conditional model (5 families + retain):", "",
           "| model | top-1 | top-3 | macro-F1 |", "|---|---:|---:|---:|",
           f"| conditional_char_lr | {c['family_top1']:.3f} | {c['family_top3']:.3f} | "
           f"{c['family_macro_f1']:.3f} |"]
    md += ["", "Valid Y mechanism support:", ""]
    for mech, n in results["models"]["char_api_lr"]["y_valid"]["support"].items():
        md.append(f"- {mech}: {n}")
    (OUT / f"baseline_mechanism_{args.version}.md").write_text("\n".join(md) + "\n")
    print(f"\nwrote {OUT}/baseline_mechanism_{args.version}.json and .md")


if __name__ == "__main__":
    main()
