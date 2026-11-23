"""Abstention / calibration stage for the mechanism model (v0.5 data).

The joint mechanism classifier suggests a mechanism for most M/N rows, which
makes it useless as a tool: a false suggestion ("use this safe API") is the
expensive error, while staying silent costs little. This script asks whether a
calibrated abstention policy can be deployed on the same features, and reports
the honest risk-coverage curve when it cannot.

Variants, all fitted on train and tuned on grouped out-of-fold predictions:

  one_stage_argmax_balanced   - current model, argmax (no abstention)
  one_stage_argmax_unbalanced - plain LR, argmax
  one_stage_margin            - balanced LR, suggest only when
                                max P(mechanism) - P(retain) >= margin
  two_stage                   - binary "has a safe mechanism" gate, then the
                                conditional mechanism model on flagged rows

The margin / gate threshold is selected on train out-of-fold predictions to
maximise suggestion recall subject to suggestion precision >= TARGET; the
frozen valid split is scored once with that policy. Test stays sealed.

Writes out/abstention_v0.1.{json,md}.
"""

from __future__ import annotations

import json
from collections import Counter
from pathlib import Path

import numpy as np
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import accuracy_score
from sklearn.model_selection import StratifiedGroupKFold
from sklearn.pipeline import Pipeline

from baseline_mechanism import MECH, SelectField, text_api

OUT = Path(__file__).resolve().parent / "out"
DATASET = OUT / "mechanism_dataset_v05.jsonl"
TARGET = 0.80          # required precision of suggested mechanisms (row is Y)
SEED = 0
N_FOLDS = 5


def load():
    rows = [json.loads(x) for x in DATASET.open() if x.strip()]
    train = [r for r in rows if r["split"] == "train"]
    valid = [r for r in rows if r["split"] == "valid"]
    test = [r for r in rows if r["split"] == "test"]
    assert (len(valid), len(test)) == (87, 130), "valid/test must stay frozen"
    return train, valid, test


def feats():
    return Pipeline([
        ("sel", SelectField("text")),
        ("tfidf", TfidfVectorizer(analyzer="char_wb", ngram_range=(2, 5),
                                  sublinear_tf=True, min_df=2)),
    ])


def full_pipeline(balanced: bool):
    from sklearn.pipeline import FeatureUnion
    from sklearn.preprocessing import OneHotEncoder
    return Pipeline([
        ("feat", FeatureUnion([
            ("tfidf", feats()),
            ("api", Pipeline([
                ("sel", SelectField("api")),
                ("oh", OneHotEncoder(handle_unknown="ignore")),
            ])),
        ])),
        ("clf", LogisticRegression(class_weight="balanced" if balanced else None,
                                   max_iter=3000, C=1.0, random_state=SEED)),
    ])


def oof_multiclass(train, balanced):
    """Grouped out-of-fold probabilities for every train row."""
    y = np.array([r["mechanism"] for r in train])
    groups = np.array([r["repo_key"] for r in train])
    x = text_api(train)
    skf = StratifiedGroupKFold(n_splits=N_FOLDS, shuffle=True, random_state=SEED)
    oof = np.zeros((len(y), len(MECH)))
    for tr, te in skf.split(x, y, groups):
        model = full_pipeline(balanced)
        model.fit([x[i] for i in tr], y[tr])
        proba = model.predict_proba([x[i] for i in te])
        for col, cls in enumerate(model.classes_):
            oof[te, MECH.index(cls)] = proba[:, col]
    return oof


def oof_binary_gate(train):
    y = np.array([0 if r["mechanism"] == "retain" else 1 for r in train])
    groups = np.array([r["repo_key"] for r in train])
    x = text_api(train)
    skf = StratifiedGroupKFold(n_splits=N_FOLDS, shuffle=True, random_state=SEED)
    oof = np.zeros(len(y))
    for tr, te in skf.split(x, y, groups):
        model = Pipeline([
            ("feat", full_pipeline(True).named_steps["feat"]),
            ("clf", LogisticRegression(class_weight="balanced", max_iter=3000,
                                       C=1.0, random_state=SEED)),
        ])
        model.fit([x[i] for i in tr], y[tr])
        oof[te] = model.predict_proba([x[i] for i in te])[:, 1]
    return oof


def policy_metrics(rows, flagged, mechanism_pred):
    """Metrics of a suggest/abstain policy over a set of labelled rows."""
    is_y = np.array([r["mechanism"] != "retain" for r in rows])
    flagged = np.asarray(flagged, dtype=bool)
    mech = np.array([r["mechanism"] for r in rows])
    pred = np.array(mechanism_pred)
    n_flag = int(flagged.sum())
    precision = float(is_y[flagged].mean()) if n_flag else None
    recall = float(flagged[is_y].mean()) if is_y.any() else None
    false_flag = float(flagged[~is_y].mean()) if (~is_y).any() else None
    correct = int(((mech == pred) & flagged & is_y).sum())
    return {
        "rows": len(rows),
        "flagged": n_flag,
        "suggestion_precision": precision,
        "suggestion_recall": recall,
        "false_flag_rate_on_retain": false_flag,
        "mechanism_top1_among_flagged": (correct / n_flag) if n_flag else None,
    }


def choose_margin(train, oof, target=TARGET):
    """Pick the smallest margin whose OOF suggestion precision clears target."""
    is_y = np.array([r["mechanism"] != "retain" for r in train])
    mech = np.array([r["mechanism"] for r in train])
    best = None
    for m in np.arange(-0.95, 0.96, 0.05):
        score = oof[:, :-1].max(axis=1) - oof[:, -1]  # max mechanism minus retain
        flagged = score >= m
        if not flagged.any():
            continue
        precision = is_y[flagged].mean()
        recall = flagged[is_y].mean()
        if precision >= target:
            pred = np.array(MECH[:-1])[oof[:, :-1].argmax(axis=1)]
            best = {"margin": float(m), "precision": float(precision),
                    "recall": float(recall), "flagged": int(flagged.sum()),
                    "mechanism_top1": float(((mech == pred) & flagged & is_y).mean()
                                            if flagged.any() else 0.0)}
    return best


def choose_gate_threshold(train, gate_oof, target=TARGET):
    is_y = np.array([r["mechanism"] != "retain" for r in train])
    best = None
    for t in np.arange(0.05, 0.96, 0.05):
        flagged = gate_oof >= t
        if not flagged.any():
            continue
        precision = is_y[flagged].mean()
        if precision >= target:
            best = {"threshold": float(t), "precision": float(precision),
                    "recall": float(flagged[is_y].mean()),
                    "flagged": int(flagged.sum())}
    return best


def bootstrap_ci(rows, flagged, mechanism_pred, field, n_boot=2000):
    rng = np.random.default_rng(1234)
    is_y = np.array([r["mechanism"] != "retain" for r in rows])
    flagged = np.asarray(flagged, dtype=bool)
    vals = []
    for _ in range(n_boot):
        idx = rng.integers(0, len(rows), len(rows))
        f, y = flagged[idx], is_y[idx]
        if field == "precision":
            vals.append(y[f].mean() if f.any() else np.nan)
        else:
            vals.append(f[y].mean() if y.any() else np.nan)
    vals = np.asarray(vals, dtype=float)
    vals = vals[~np.isnan(vals)]
    if not len(vals):
        return None
    return [float(np.percentile(vals, 2.5)), float(np.percentile(vals, 97.5))]


def fmt(x, nd=3):
    return "n/a" if x is None else f"{x:.{nd}f}"


def main():
    train, valid, test = load()
    results = {"target_precision": TARGET, "sizes": {"train": len(train),
                                                     "valid": len(valid),
                                                     "test_sealed": len(test)}}

    # one-stage, balanced (current model) and unbalanced
    for tag, balanced in (("balanced", True), ("unbalanced", False)):
        oof = oof_multiclass(train, balanced)
        model = full_pipeline(balanced)
        model.fit(text_api(train), [r["mechanism"] for r in train])
        proba = model.predict_proba(text_api(valid))
        full = np.zeros((len(valid), len(MECH)))
        for col, cls in enumerate(model.classes_):
            full[:, MECH.index(cls)] = proba[:, col]
        pred = [MECH[int(j)] for j in full.argmax(axis=1)]
        # no-abstention baseline: the model always answers with its argmax class;
        # "flagged" means it argued for a mechanism rather than retain.
        argmax_policy = policy_metrics(valid, [p != "retain" for p in pred], pred)
        chosen = choose_margin(train, oof)
        if chosen:
            score_v = full[:, :-1].max(axis=1) - full[:, -1]
            flagged = score_v >= chosen["margin"]
            mech_pred = [MECH[int(j)] for j in full[:, :-1].argmax(axis=1)]
            tuned = policy_metrics(valid, flagged, mech_pred)
            tuned["cv_selected"] = chosen
            tuned["ci95"] = {
                "suggestion_precision": bootstrap_ci(valid, flagged, mech_pred, "precision"),
                "suggestion_recall": bootstrap_ci(valid, flagged, mech_pred, "recall"),
            }
        else:
            tuned = None
        results[f"one_stage_{tag}"] = {"argmax": argmax_policy, "margin_policy": tuned,
                                       "cv_curve": {k: v for k, v in (chosen or {}).items()}}

    # two-stage: binary gate + conditional mechanism model
    gate_oof = oof_binary_gate(train)
    gate = Pipeline([
        ("feat", full_pipeline(True).named_steps["feat"]),
        ("clf", LogisticRegression(class_weight="balanced", max_iter=3000,
                                   C=1.0, random_state=SEED)),
    ])
    gate.fit(text_api(train), [0 if r["mechanism"] == "retain" else 1 for r in train])
    gate_v = gate.predict_proba(text_api(valid))[:, 1]
    cond = Pipeline([
        ("tfidf", TfidfVectorizer(analyzer="char_wb", ngram_range=(2, 5),
                                  sublinear_tf=True, min_df=2)),
        ("clf", LogisticRegression(class_weight="balanced", max_iter=3000,
                                   C=1.0, random_state=SEED)),
    ])
    tr_y = [r for r in train if r["mechanism"] != "retain"]
    cond.fit([r["old_snippet"] for r in tr_y], [r["mechanism"] for r in tr_y])
    cond_pred = [list(cond.classes_)[int(j)] for j in cond.predict_proba(
        [r["old_snippet"] for r in valid]).argmax(axis=1)]
    gate_choice = choose_gate_threshold(train, gate_oof)
    if gate_choice:
        flagged = gate_v >= gate_choice["threshold"]
        ts = policy_metrics(valid, flagged, cond_pred)
        ts["cv_selected"] = gate_choice
        ts["ci95"] = {
            "suggestion_precision": bootstrap_ci(valid, flagged, cond_pred, "precision"),
            "suggestion_recall": bootstrap_ci(valid, flagged, cond_pred, "recall"),
        }
    else:
        ts = None
    results["two_stage"] = {
        "policy": ts,
        "gate_curve_cv": {k: v for k, v in (gate_choice or {}).items()},
    }

    # diagnostic: best achievable suggestion precision on valid at any threshold
    oof_bal = oof_multiclass(train, True)
    model = full_pipeline(True)
    model.fit(text_api(train), [r["mechanism"] for r in train])
    proba = model.predict_proba(text_api(valid))
    full = np.zeros((len(valid), len(MECH)))
    for col, cls in enumerate(model.classes_):
        full[:, MECH.index(cls)] = proba[:, col]
    curve = []
    for m in np.arange(-0.95, 0.96, 0.1):
        score = full[:, :-1].max(axis=1) - full[:, -1]
        flagged = score >= m
        if flagged.any():
            is_y = np.array([r["mechanism"] != "retain" for r in valid])
            curve.append({"margin": round(float(m), 2),
                          "flagged": int(flagged.sum()),
                          "precision": round(float(is_y[flagged].mean()), 3),
                          "recall": round(float(flagged[is_y].mean()), 3)})
    results["valid_curve_one_stage_balanced"] = curve
    results["max_valid_precision"] = max((c["precision"] for c in curve), default=None)

    json.dump(results, open(OUT / "abstention_v0.1.json", "w"),
              indent=2, ensure_ascii=False)

    md = ["# Abstention stage (v0.5 mechanism data)", "",
          f"Requirement: suggested mechanisms should be right at least {TARGET:.0%} of the time;",
          "silence is cheap, a wrong suggestion is not. Policies tuned on grouped",
          "out-of-fold train predictions, scored once on the frozen 87-row valid split.", ""]
    for key in ("one_stage_balanced", "one_stage_unbalanced"):
        r = results[key]
        md += [f"## {key}", "",
               f"argmax (no abstention): flagged {r['argmax']['flagged']}/{r['argmax']['rows']}, "
               f"suggestion precision {fmt(r['argmax']['suggestion_precision'])}, "
               f"mechanism top-1 among flagged {fmt(r['argmax']['mechanism_top1_among_flagged'])}"]
        if r["margin_policy"]:
            t = r["margin_policy"]
            ci = t["ci95"]["suggestion_precision"]
            md.append(f"tuned margin ({r['cv_curve']['margin']:+.2f}): flagged "
                      f"{t['flagged']}/{t['rows']}, precision {fmt(t['suggestion_precision'])} "
                      f"({'n/a' if ci is None else f'{ci[0]:.3f}-{ci[1]:.3f}'}), "
                      f"recall {fmt(t['suggestion_recall'])}, mechanism top-1 "
                      f"{fmt(t['mechanism_top1_among_flagged'])}")
        else:
            md.append("no margin reaches the precision target on CV")
        md.append("")
    ts = results["two_stage"]["policy"]
    md += ["## two_stage", ""]
    if ts:
        ci = ts["ci95"]["suggestion_precision"]
        md += [f"gate threshold {results['two_stage']['gate_curve_cv']['threshold']:.2f}: flagged "
               f"{ts['flagged']}/{ts['rows']}, precision {fmt(ts['suggestion_precision'])} "
               f"({'n/a' if ci is None else f'{ci[0]:.3f}-{ci[1]:.3f}'}), "
               f"recall {fmt(ts['suggestion_recall'])}, mechanism top-1 "
               f"{fmt(ts['mechanism_top1_among_flagged'])}"]
    else:
        md.append("no gate threshold reaches the precision target on CV")
    md += ["", "## Valid risk-coverage curve (one-stage, balanced)", "",
           "| margin | flagged | suggestion precision | recall |",
           "|---:|---:|---:|---:|"]
    for c in results["valid_curve_one_stage_balanced"]:
        md.append(f"| {c['margin']:+.2f} | {c['flagged']} | {c['precision']:.3f} | {c['recall']:.3f} |")
    md += ["", f"Best suggestion precision reachable on valid: {fmt(results['max_valid_precision'])} "
           f"(target {TARGET:.0%})."]
    (OUT / "abstention_v0.1.md").write_text("\n".join(md) + "\n")
    print(json.dumps({k: results[k] for k in
                      ("one_stage_balanced", "two_stage", "max_valid_precision")},
                     indent=2, default=str)[:3000])
    print(f"\nwrote {OUT}/abstention_v0.1.json and .md")


if __name__ == "__main__":
    main()
