"""Build a blind sample for the second spot-check.

12 rows per core label, round-robin across sources, deterministic seed. The
output has no label/action/rationale/mechanism/kind fields so a fresh annotator
cannot see the existing decision.
"""

from __future__ import annotations

import json
import random
from collections import defaultdict
from pathlib import Path

OUT = Path(__file__).resolve().parent.parent / "out"
DEST = Path(__file__).resolve().parent / "spotcheck2_blind.jsonl"
FIELDS = ("id", "source", "path", "api_guess", "fn_id", "old_snippet", "safe_snippet")


def main() -> int:
    rows = [json.loads(x) for x in (OUT / "transitions_core_v0.2_draft.jsonl").open() if x.strip()]
    by_label = defaultdict(list)
    for r in rows:
        by_label[r["label"]].append(r)
    rng = random.Random(11)
    sample = []
    for label in ("Y", "M", "N"):
        pool = by_label[label]
        by_source = defaultdict(list)
        for r in pool:
            by_source[r.get("source")].append(r)
        for rs in by_source.values():
            rng.shuffle(rs)
        take = []
        while len(take) < 12 and any(by_source.values()):
            for src in sorted(by_source):
                if by_source[src] and len(take) < 12:
                    take.append(by_source[src].pop())
        sample.extend(take)
    sample.sort(key=lambda r: (r["label"], r["id"]))
    with DEST.open("w") as f:
        for r in sample:
            f.write(json.dumps({k: r.get(k) for k in FIELDS}, ensure_ascii=False) + "\n")
    print(json.dumps({
        "rows": len(sample),
        "by_label": {l: sum(1 for r in sample if r["label"] == l) for l in ("Y", "M", "N")},
        "by_source": {s: sum(1 for r in sample if r["source"] == s) for s in ("cvefixes", "cratesio", "rustsec")},
        "out": str(DEST),
    }, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
