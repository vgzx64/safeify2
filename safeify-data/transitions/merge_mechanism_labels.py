"""Merge mechanism-label batches and validate them.

Fails on missing/extra ids, an unknown mechanism, a family that does not match
the taxonomy, an unknown confidence, or missing evidence.
"""

from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path

from mechanism_taxonomy import FAMILIES, MECHANISMS, family as family_of

HERE = Path(__file__).resolve().parent
DEST = HERE / "adjudication/mechanisms"
CONF = {"high", "medium", "low"}


def load(path: Path) -> list[dict]:
    return [json.loads(x) for x in path.open() if x.strip()]


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--write", action="store_true")
    args = ap.parse_args()

    queue = json.loads((DEST / "queue.json").read_text())
    problems: list[str] = []
    merged: dict[str, dict] = {}
    for batch in queue["batches"]:
        src = DEST / batch["file"]
        lab = DEST / batch["file"].replace("batch_", "labels_batch_")
        if not lab.exists():
            problems.append(f"{batch['file']}: labels missing")
            continue
        inputs = load(src)
        labels = load(lab)
        want = [r["id"] for r in inputs]
        got = [r.get("id") for r in labels]
        if len(got) != len(set(got)):
            problems.append(f"{batch['file']}: duplicate ids")
        if set(want) - set(got):
            problems.append(f"{batch['file']}: missing {len(set(want) - set(got))} ids")
        if set(got) - set(want):
            problems.append(f"{batch['file']}: extra ids {sorted(set(got) - set(want))[:3]}")
        for row in labels:
            rid = row.get("id")
            if rid not in set(want):
                continue
            mech = row.get("mechanism")
            if mech not in MECHANISMS:
                problems.append(f"{rid}: bad mechanism {mech!r}")
                continue
            if row.get("family") != family_of(mech) or row.get("family") not in FAMILIES:
                problems.append(f"{rid}: family {row.get('family')!r} != {family_of(mech)}")
            if row.get("confidence") not in CONF:
                problems.append(f"{rid}: bad confidence {row.get('confidence')!r}")
            if not (row.get("evidence_new") or "").strip():
                problems.append(f"{rid}: missing evidence_new")
            merged[rid] = row

    if problems:
        print(json.dumps({"ok": False, "problems": problems[:50]}, indent=2))
        return 1
    stats = {
        "ok": True,
        "rows": len(merged),
        "mechanisms": dict(Counter(r["mechanism"] for r in merged.values()).most_common()),
        "families": dict(Counter(r["family"] for r in merged.values()).most_common()),
        "confidence": dict(Counter(r["confidence"] for r in merged.values()).most_common()),
    }
    (DEST / "label_stats.json").write_text(json.dumps(stats, indent=2) + "\n")
    print(json.dumps(stats, indent=2))
    if args.write:
        with (DEST / "labeled.jsonl").open("w") as f:
            for r in merged.values():
                f.write(json.dumps(r, ensure_ascii=False) + "\n")
        print(f"wrote {DEST/'labeled.jsonl'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
