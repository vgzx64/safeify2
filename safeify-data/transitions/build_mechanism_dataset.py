"""Build the mechanism dataset from the v0.3 core and the mechanism labels.

Every Y row gets a fine mechanism class (from labels_safe.csv where it exists,
otherwise from the mechanism audit) and a family. M/N rows get `retain`.
`retain` is the model's abstention class: a safe mechanism would be wrong there.

Writes out/mechanism_dataset.jsonl and out/mechanism_dataset_stats.json.
"""

from __future__ import annotations

import csv
import json
from collections import Counter
from pathlib import Path

from mechanism_taxonomy import MECHANISMS, canon, family

HERE = Path(__file__).resolve().parent
OUT = HERE / "out"


def main() -> int:
    core = [json.loads(x) for x in (OUT / "transitions_core_v0.3_draft.jsonl").open() if x.strip()]
    safe = {r["id"]: r for r in csv.DictReader((HERE / "labels_safe.csv").open())}
    audit = {}
    path = HERE / "adjudication/mechanisms/labeled.jsonl"
    if path.exists():
        audit = {r["id"]: r for r in
                 (json.loads(x) for x in path.open() if x.strip())}

    rows, missing = [], []
    for r in core:
        label = r["label"]
        if label == "Y":
            if r["id"] in safe:
                mech = canon(safe[r["id"]]["mechanism"])
                src = "labels_safe"
            elif r["id"] in audit:
                mech = audit[r["id"]]["mechanism"]
                src = "audit"
            else:
                missing.append(r["id"])
                continue
        else:
            mech, src = "retain", "label"
        assert mech in MECHANISMS or mech == "retain", mech
        rows.append({
            "id": r["id"],
            "split": r["split"],
            "source": r["source"],
            "repo_key": r["repo_key"],
            "label": label,
            "mechanism": mech,
            "family": family(mech),
            "mechanism_source": src,
            "api_guess": r.get("api_guess") or r.get("api_old") or "unknown",
            "old_snippet": r["old_snippet"],
            "safe_snippet": r["safe_snippet"],
        })

    assert not missing, f"Y rows without a mechanism: {missing[:5]}"
    train = [r for r in rows if r["split"] == "train"]
    stats = {
        "rows": len(rows),
        "by_split": dict(Counter(r["split"] for r in rows)),
        "by_mechanism": dict(Counter(r["mechanism"] for r in rows).most_common()),
        "by_family": dict(Counter(r["family"] for r in rows).most_common()),
        "train_mechanisms": dict(Counter(r["mechanism"] for r in train).most_common()),
        "valid_y_mechanisms": dict(Counter(r["mechanism"] for r in rows
                                           if r["split"] == "valid" and r["mechanism"] != "retain").most_common()),
        "test_y_mechanisms_sealed": dict(Counter(r["mechanism"] for r in rows
                                                 if r["split"] == "test" and r["mechanism"] != "retain").most_common()),
    }
    with (OUT / "mechanism_dataset.jsonl").open("w") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    (OUT / "mechanism_dataset_stats.json").write_text(json.dumps(stats, indent=2) + "\n")
    print(json.dumps(stats, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
