"""Merge adjudication batch labels and validate them against the input IDs."""

from __future__ import annotations

import json
from collections import Counter
from pathlib import Path

HERE = Path(__file__).resolve().parent


def main() -> int:
    inputs = [json.loads(x) for x in (HERE / "pilot_001.jsonl").open()]
    labels = []
    for name in ("labels_001a.jsonl", "labels_001b.jsonl"):
        p = HERE / name
        if p.exists():
            labels.extend(json.loads(x) for x in p.open() if x.strip())
    want = {r["id"] for r in inputs}
    got = {r["id"] for r in labels}
    missing = sorted(want - got)
    extra = sorted(got - want)
    dupes = [k for k, v in Counter(r["id"] for r in labels).items() if v > 1]
    with (HERE / "labels_001.jsonl").open("w") as f:
        for r in labels:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    stats = {
        "inputs": len(inputs),
        "labels": len(labels),
        "missing": missing,
        "extra": extra,
        "duplicates": dupes,
        "replaceability": dict(Counter(r.get("replaceability") for r in labels)),
        "action": dict(Counter(r.get("action") for r in labels)),
        "vetoed": sum(bool(r.get("veto")) for r in labels),
    }
    (HERE / "labels_001_stats.json").write_text(json.dumps(stats, indent=2) + "\n")
    print(json.dumps(stats, indent=2))
    return 0 if not (missing or extra or dupes) else 1


if __name__ == "__main__":
    raise SystemExit(main())
