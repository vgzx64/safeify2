"""Does a classifier trained on rule-derived hazard labels predict human labels?

The hazard baseline (baseline_hazard.py) is trained and scored on rule labels,
which makes it a rule distiller. This script asks the useful question instead:
train on rule-labelled train rows, then evaluate against **human** hazard labels
on the frozen valid split. It also reports how often the rules themselves agree
with the human labels, which bounds what any rule-trained model can reach.
"""

from __future__ import annotations

import json
from collections import Counter
from pathlib import Path

import numpy as np
from sklearn.metrics import (accuracy_score, confusion_matrix, f1_score,
                             precision_recall_fscore_support)
from sklearn.metrics import cohen_kappa_score

from baseline_hazard import DETERMINABLE, model as make_model

HERE = Path(__file__).resolve().parent
OUT = HERE / "out"
DEST = HERE / "adjudication/hazard_valid"


def load_labels() -> dict[str, str]:
    out = {}
    for path in sorted(DEST.glob("labels_batch_*.jsonl")):
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
    return {
        "n": len(y),
        "accuracy": float(accuracy_score(y, pred)),
        "macro_f1": float(f1_score(y, pred, labels=classes, average="macro",
                                   zero_division=0)),
        "per_class": {c: {"precision": float(p[i]), "recall": float(r[i]),
                          "f1": float(f[i]), "support": int(s[i])}
                      for i, c in enumerate(classes)},
        "top_confusions": [{"true": a, "pred": b, "n": n} for a, b, n in pairs],
    }


def main() -> int:
    human = load_labels()
    rows = [json.loads(x) for x in (OUT / "mechanism_dataset_v05.jsonl").open() if x.strip()]
    rules = {r["id"]: r["hazard"] for r in
             (json.loads(x) for x in (OUT / "hazard_labels.jsonl").open() if x.strip())}
    train = [r for r in rows if r["split"] == "train"]
    valid = [r for r in rows if r["split"] == "valid"]
    report = {"human_valid_labels": len(human), "valid_rows": len(valid)}

    # rule vs human on valid
    common = [r for r in valid if r["id"] in human]
    report["rule_vs_human"] = {
        "rows": len(common),
        "agreement": float(np.mean([rules[r["id"]] == human[r["id"]] for r in common])),
        "kappa": float(cohen_kappa_score([rules[r["id"]] for r in common],
                                         [human[r["id"]] for r in common])),
        "human_distribution": dict(Counter(human[r["id"]] for r in common).most_common()),
    }

    tr = [r for r in train if rules[r["id"]] in DETERMINABLE]
    va = [r for r in common if human[r["id"]] in DETERMINABLE]
    x_tr = [{"old_snippet": r["old_snippet"], "api_guess": r.get("api_guess")} for r in tr]
    x_va = [{"old_snippet": r["old_snippet"], "api_guess": r.get("api_guess")} for r in va]
    m = make_model()
    m.fit(x_tr, [rules[r["id"]] for r in tr])

    # predictions vs human labels
    proba = m.predict_proba(x_va)
    classes = list(m.classes_)
    pred = [classes[int(j)] for j in proba.argmax(axis=1)]
    human_rows = [{"hazard": human[r["id"]]} for r in va]
    report["model_vs_human"] = metrics(human_rows, pred, DETERMINABLE)

    # same model, same rows, vs rule labels (the distillation ceiling)
    rule_rows = [{"hazard": rules[r["id"]]} for r in va]
    report["model_vs_rules_same_rows"] = metrics(rule_rows, pred, DETERMINABLE)

    json.dump(report, open(OUT / "hazard_human_v0.1.json", "w"),
              indent=2, ensure_ascii=False)
    md = ["# Hazard labels: human evaluation (valid split)", "",
          f"Human labels collected for {len(human)} of {len(valid)} valid rows.", "",
          "## Rules vs human annotators", "",
          f"- agreement {report['rule_vs_human']['agreement']:.3f}, "
          f"Cohen kappa {report['rule_vs_human']['kappa']:.3f} on "
          f"{report['rule_vs_human']['rows']} rows", "",
          "## Model (trained on rule labels) vs human labels", "",
          f"- rows {report['model_vs_human']['n']}, accuracy "
          f"{report['model_vs_human']['accuracy']:.3f}, macro F1 "
          f"{report['model_vs_human']['macro_f1']:.3f}", "",
          "| hazard | precision | recall | F1 | support |", "|---|---:|---:|---:|---:|"]
    for c, v in report["model_vs_human"]["per_class"].items():
        md.append(f"| {c} | {v['precision']:.3f} | {v['recall']:.3f} | {v['f1']:.3f} | {v['support']} |")
    md += ["", "Model vs rule labels on the same rows: accuracy "
           f"{report['model_vs_rules_same_rows']['accuracy']:.3f}, macro F1 "
           f"{report['model_vs_rules_same_rows']['macro_f1']:.3f}.", "",
           "Top confusions against human labels:", ""]
    for c in report["model_vs_human"]["top_confusions"]:
        md.append(f"- {c['true']} -> {c['pred']}: {c['n']}")
    (OUT / "hazard_human_v0.1.md").write_text("\n".join(md) + "\n")
    print(json.dumps({k: report[k] for k in ("rule_vs_human", "model_vs_human")},
                     indent=2, default=str)[:2500])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
