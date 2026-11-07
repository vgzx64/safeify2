"""Merge gate-batch labels into reviewed_all.jsonl with strict validation.

Each chunk file ``gate_aNN.jsonl`` is paired with ``labels_gate_aNN.jsonl``.
Validates: same id set, no duplicates, required fields, legal enum values.
Missing or extra labels are reported and the merge fails so the batch can be
re-run instead of silently shrinking.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path

HERE = Path(__file__).resolve().parent
TAGS = [f"a{i:02d}" for i in range(1, 7)] + [f"b{i:02d}" for i in range(1, 7)]
LABELS = {"Y", "M", "N", "U"}
ACTIONS = {"replace", "guard", "encapsulate", "keep", "unknown"}
CONF = {"high", "medium", "low"}


def load(path: Path) -> list[dict]:
    return [json.loads(x) for x in path.open() if x.strip()]


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--strict", action="store_true", help="fail when a chunk has no labels file")
    args = ap.parse_args()
    reviewed = load(HERE / "reviewed_all.jsonl")
    by_id = {r.get("queue_id") or r.get("id"): r for r in reviewed}
    base = len(by_id)
    problems: list[str] = []
    added = 0
    added_ids: set[str] = set()
    for tag in TAGS:
        inputs = HERE / f"gate_{tag}.jsonl"
        labels = HERE / f"labels_gate_{tag}.jsonl"
        if not labels.exists():
            if args.strict:
                problems.append(f"{tag}: labels file missing")
            continue
        ins = load(inputs)
        labs = load(labels)
        want = {r["id"] for r in ins}
        got = Counter(r.get("id") for r in labs)
        missing = want - set(got)
        extra = set(got) - want
        dupes = [k for k, v in got.items() if v > 1]
        if missing:
            problems.append(f"{tag}: missing {len(missing)} ids e.g. {sorted(missing)[:3]}")
        if extra:
            problems.append(f"{tag}: extra ids {sorted(extra)[:3]}")
        if dupes:
            problems.append(f"{tag}: duplicate ids {dupes[:3]}")
        for lab in labs:
            rid = lab.get("id")
            if lab.get("replaceability") not in LABELS:
                problems.append(f"{tag}: bad replaceability {rid}")
                continue
            if lab.get("action") not in ACTIONS:
                problems.append(f"{tag}: bad action {rid}")
                continue
            if lab.get("confidence") not in CONF:
                problems.append(f"{tag}: bad confidence {rid}")
                continue
            if rid in by_id:
                # already merged in an earlier partial run; idempotent skip
                continue
            src = next(r for r in ins if r["id"] == rid)
            row = dict(src)
            row.update(lab)
            by_id[rid] = row
            added += 1
            added_ids.add(rid)
    if problems:
        print("FAILED")
        for p in problems[:40]:
            print(" -", p)
        return 1
    rows = list(by_id.values())
    with (HERE / "reviewed_all.jsonl").open("w") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    suspects = [
        r.get("queue_id") or r.get("id")
        for r in rows
        if (r.get("queue_id") or r.get("id")) in added_ids
        and r.get("replaceability") == "Y"
        and "unsafe" in (r.get("safe_snippet") or "")
    ]
    stats = {
        "before": base,
        "added": added,
        "now": len(rows),
        "replaceability": dict(Counter(r.get("replaceability") for r in rows)),
        "vetoed": sum(1 for r in rows if r.get("veto")),
        "sources": dict(Counter(r.get("source") for r in rows)),
        "y_with_unsafe_in_new_snippet": len(suspects),
    }
    (HERE / "reviewed_all_stats.json").write_text(json.dumps(stats, indent=2) + "\n")
    print(json.dumps(stats, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
