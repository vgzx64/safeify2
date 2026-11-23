"""Merge expansion adjudication batches into one labeled JSONL and validate them.

Fails loudly on: missing/extra/duplicate ids, illegal enum values, a Y label
whose new snippet still contains an unsafe operation, an M label without quoted
evidence, or a U label without a veto reason.
"""

from __future__ import annotations

import argparse
import json
import re
from collections import Counter
from pathlib import Path

HERE = Path(__file__).resolve().parent
DEST = HERE / "adjudication/expansion"

from mechanism_rules import UNSAFE
LABELS = {"Y", "M", "N", "U"}
ACTIONS = {"replace", "guard", "encapsulate", "keep", "unknown"}
CONF = {"high", "medium", "low"}


def load(path: Path) -> list[dict]:
    return [json.loads(x) for x in path.open() if x.strip()]


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--write", action="store_true", help="write labeled.jsonl on success")
    args = ap.parse_args()

    queue = json.loads((DEST / "queue.json").read_text())
    pool = {}
    for line in (HERE / "out/expansion_pool_draft.jsonl").open():
        if line.strip():
            r = json.loads(line)
            pool[r["id"]] = r
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
        missing = set(want) - set(got)
        extra = set(got) - set(want)
        if missing:
            problems.append(f"{batch['file']}: missing {len(missing)} ids e.g. {sorted(missing)[:2]}")
        if extra:
            problems.append(f"{batch['file']}: extra ids {sorted(extra)[:2]}")
        by_id = {r["id"]: r for r in inputs}
        for row in labels:
            rid = row.get("id")
            if rid not in by_id:
                continue
            if row.get("replaceability") not in LABELS:
                problems.append(f"{rid}: bad replaceability {row.get('replaceability')!r}")
                continue
            if row.get("action") not in ACTIONS:
                problems.append(f"{rid}: bad action {row.get('action')!r}")
                continue
            if row.get("confidence") not in CONF:
                problems.append(f"{rid}: bad confidence {row.get('confidence')!r}")
                continue
            src_row = pool[rid]
            new_text = src_row.get("new_snippet") or src_row.get("safe_snippet") or ""
            if row["replaceability"] == "Y" and UNSAFE.search(new_text):
                problems.append(f"{rid}: Y but new snippet still has an unsafe operation")
            if row["replaceability"] in ("Y", "M") and not (row.get("evidence_new") or "").strip():
                problems.append(f"{rid}: {row['replaceability']} without evidence_new")
            if row["replaceability"] == "U" and not row.get("veto"):
                problems.append(f"{rid}: U without veto=true")
            if row["replaceability"] == "U" and not (row.get("veto_reason") or "").strip():
                problems.append(f"{rid}: U without veto_reason")
            base = dict(src_row)
            base.update(row)
            base["queue_id"] = rid
            base["review_status"] = "reviewed"
            merged[rid] = base

    if problems:
        print(json.dumps({"ok": False, "problems": problems[:60],
                          "n_problems": len(problems)}, indent=2))
        return 1

    rows = list(merged.values())
    stats = {
        "ok": True,
        "rows": len(rows),
        "labels": dict(Counter(r["replaceability"] for r in rows)),
        "by_kind_label": {f"{k}/{l}": c for (k, l), c in
                          Counter((r["kind"], r["replaceability"]) for r in rows).most_common()},
        "by_source_label": {f"{s}/{l}": c for (s, l), c in
                            Counter((r["source"], r["replaceability"]) for r in rows).most_common()},
        "by_confidence": dict(Counter(r["confidence"] for r in rows).most_common()),
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
