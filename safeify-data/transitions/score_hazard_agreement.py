"""Agreement between the hazard annotators and the rule-derived labels."""

from __future__ import annotations

import json
from collections import Counter
from pathlib import Path

from sklearn.metrics import cohen_kappa_score

HERE = Path(__file__).resolve().parent
OUT = HERE / "out"
DEST = HERE / "adjudication/hazard"


def load(path: Path) -> list[dict]:
    return [json.loads(x) for x in path.open() if x.strip()]


def main() -> int:
    sample = [r["id"] for r in load(DEST / "sample.jsonl")]
    rules = {r["id"]: r["hazard"] for r in load(OUT / "hazard_labels.jsonl")}
    ann = {}
    for tag, name in (("a", "labels_haz_a.jsonl"), ("b", "labels_haz_b.jsonl")):
        path = DEST / name
        if path.exists():
            ann[tag] = {r["id"]: r["hazard"] for r in load(path)}
        else:
            ann[tag] = None
    report = {"rows": len(sample), "annotators": list(k for k, v in ann.items() if v)}
    pairs = {}
    ids_common = sample
    for tag, values in ann.items():
        if values is None:
            continue
        ids = [i for i in ids_common if i in values]
        pairs[f"{tag}_rules_kappa"] = float(cohen_kappa_score(
            [values[i] for i in ids], [rules[i] for i in ids]))
        pairs[f"{tag}_rules_agreement"] = float(sum(values[i] == rules[i] for i in ids) / len(ids))
        report[f"distribution_{tag}"] = dict(Counter(values[i] for i in ids).most_common())
    if ann.get("a") and ann.get("b"):
        ids = [i for i in ids_common if i in ann["a"] and i in ann["b"]]
        pairs["a_b_kappa"] = float(cohen_kappa_score(
            [ann["a"][i] for i in ids], [ann["b"][i] for i in ids]))
        pairs["a_b_agreement"] = float(sum(ann["a"][i] == ann["b"][i] for i in ids) / len(ids))
        pairs["a_b_disagreements"] = [
            {"id": i, "a": ann["a"][i], "b": ann["b"][i], "rule": rules[i]}
            for i in ids if ann["a"][i] != ann["b"][i]][:12]
    report["pairs"] = pairs
    (DEST / "agreement.json").write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report, indent=2)[:2500])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
