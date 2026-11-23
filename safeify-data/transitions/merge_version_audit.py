"""Merge and validate the version-history audit batches.

Each label carries a verdict (Y/M/N/U), and for Y a mechanism from the
taxonomy, with quoted evidence. Fails on missing/extra ids, unknown enum
values, a Y with unsafe code left in the new snippet, or an M/U without the
required evidence/veto.
"""

from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path

from mechanism_rules import UNSAFE
from mechanism_taxonomy import MECHANISMS, family as family_of

HERE = Path(__file__).resolve().parent
DEST = HERE / "adjudication/version_audit"
VERDICTS = {"Y", "M", "N", "U"}
CONF = {"high", "medium", "low"}


def load(path: Path) -> list[dict]:
    return [json.loads(x) for x in path.open() if x.strip()]


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--write", action="store_true")
    args = ap.parse_args()

    queue = json.loads((DEST / "queue.json").read_text())
    mined = {json.loads(x)["id"]: json.loads(x)
             for x in (HERE / "out/version_pairs.jsonl").open() if x.strip()}
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
            verdict = row.get("replaceability")
            if verdict not in VERDICTS:
                problems.append(f"{rid}: bad verdict {verdict!r}")
                continue
            if row.get("confidence") not in CONF:
                problems.append(f"{rid}: bad confidence {row.get('confidence')!r}")
            if verdict == "Y":
                mech = row.get("mechanism")
                if mech not in MECHANISMS:
                    problems.append(f"{rid}: bad mechanism {mech!r}")
                    continue
                if row.get("family") != family_of(mech):
                    problems.append(f"{rid}: family mismatch for {mech}")
                if UNSAFE.search(mined[rid]["safe_snippet"]):
                    problems.append(f"{rid}: Y but new snippet has unsafe code")
                if not (row.get("evidence_new") or "").strip():
                    problems.append(f"{rid}: Y without evidence_new")
            elif verdict == "M" and not (row.get("evidence_new") or "").strip():
                problems.append(f"{rid}: M without evidence_new")
            elif verdict == "U" and not row.get("veto"):
                problems.append(f"{rid}: U without veto=true")
            base = dict(mined[rid])
            base.update(row)
            base["queue_id"] = rid
            merged[rid] = base

    if problems:
        print(json.dumps({"ok": False, "problems": problems[:50]}, indent=2))
        return 1
    rows = list(merged.values())
    stats = {
        "ok": True,
        "rows": len(rows),
        "verdicts": dict(Counter(r["replaceability"] for r in rows).most_common()),
        "mechanisms": dict(Counter(r["mechanism"] for r in rows
                                   if r["replaceability"] == "Y").most_common()),
        "confidence": dict(Counter(r["confidence"] for r in rows).most_common()),
        "packages": len({r["package"] for r in rows}),
    }
    (DEST / "label_stats.json").write_text(json.dumps(stats, indent=2) + "\n")
    print(json.dumps(stats, indent=2))
    if args.write:
        with (DEST / "labeled.jsonl").open("w") as f:
            for r in rows:
                f.write(json.dumps(r, ensure_ascii=False) + "\n")
        print(f"wrote {DEST/'labeled.jsonl'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
