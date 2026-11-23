"""Score blind-annotation agreement for the classification task.

Compares two independent annotators (and each against the stored labels) on
the 60-row agreement sample. Binary agreement is Y vs not-Y; mechanism
agreement is exact-class agreement among rows both annotators call Y.
"""

from __future__ import annotations

import json
from collections import Counter
from pathlib import Path

from sklearn.metrics import cohen_kappa_score

HERE = Path(__file__).resolve().parent
OUT = HERE / "out"
DEST = HERE / "adjudication/agreement"


def load(path: Path) -> list[dict]:
    return [json.loads(x) for x in path.open() if x.strip()]


def main() -> int:
    sample = {r["id"]: r for r in load(DEST / "sample.jsonl")}
    stored_rows = {r["id"]: r for r in load(OUT / "mechanism_dataset_v05.jsonl")}
    ann_a = {r["id"]: r for r in load(DEST / "labels_ann_a.jsonl")}
    ann_b = {r["id"]: r for r in load(DEST / "labels_ann_b.jsonl")}
    ids = [i for i in sample if i in ann_a and i in ann_b]

    def stored_mech(i):
        m = stored_rows[i]["mechanism"]
        return "retain" if m == "retain" else m

    def y_of(rec):
        return int(rec.get("replaceability") == "Y")

    def mech_of(rec):
        return rec.get("mechanism") or "retain"

    binary = {
        "a_b": cohen_kappa_score([y_of(ann_a[i]) for i in ids],
                                 [y_of(ann_b[i]) for i in ids]),
        "a_stored": cohen_kappa_score(
            [y_of(ann_a[i]) for i in ids],
            [int(stored_rows[i]["mechanism"] != "retain") for i in ids]),
        "b_stored": cohen_kappa_score(
            [y_of(ann_b[i]) for i in ids],
            [int(stored_rows[i]["mechanism"] != "retain") for i in ids]),
        "a_b_agreement": float(sum(y_of(ann_a[i]) == y_of(ann_b[i]) for i in ids) / len(ids)),
    }
    both_y = [i for i in ids if y_of(ann_a[i]) and y_of(ann_b[i])]
    mech = {
        "n_both_y": len(both_y),
        "a_b_kappa": cohen_kappa_score([mech_of(ann_a[i]) for i in both_y],
                                       [mech_of(ann_b[i]) for i in both_y])
        if both_y else None,
        "a_b_exact": float(sum(mech_of(ann_a[i]) == mech_of(ann_b[i]) for i in both_y) / len(both_y))
        if both_y else None,
    }
    # stored-vs-annotator mechanism agreement on stored-Y rows both call Y
    for tag, ann in (("a", ann_a), ("b", ann_b)):
        rows = [i for i in both_y if stored_rows[i]["mechanism"] != "retain"]
        mech[f"{tag}_stored_kappa"] = (cohen_kappa_score(
            [mech_of(ann[i]) for i in rows],
            [stored_mech(i) for i in rows]) if rows else None)
    report = {
        "rows": len(ids),
        "verdicts": {"ann_a": dict(Counter(ann_a[i]["replaceability"] for i in ids)),
                     "ann_b": dict(Counter(ann_b[i]["replaceability"] for i in ids)),
                     "stored": dict(Counter(
                         "Y" if stored_rows[i]["mechanism"] != "retain" else "retain"
                         for i in ids))},
        "binary_agreement": binary,
        "mechanism_agreement": mech,
        "a_b_disagreements": [
            {"id": i, "a": ann_a[i]["replaceability"], "b": ann_b[i]["replaceability"],
             "a_mech": mech_of(ann_a[i]), "b_mech": mech_of(ann_b[i])}
            for i in ids if ann_a[i]["replaceability"] != ann_b[i]["replaceability"]
        ][:15],
    }
    (DEST / "agreement.json").write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report, indent=2)[:2500])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
