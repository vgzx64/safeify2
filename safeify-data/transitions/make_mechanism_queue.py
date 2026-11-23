"""Build the mechanism-label audit queue for audited Y rows without a mechanism.

Reads the v0.3 draft core, keeps `label == "Y"` rows whose id is absent from
`labels_safe.csv` (which already carries a free-text mechanism), clips the
snippets and writes batches under `adjudication/mechanisms/`.
"""

from __future__ import annotations

import argparse
import csv
import json
from collections import Counter
from pathlib import Path

HERE = Path(__file__).resolve().parent
OUT = HERE / "out"
DEST = HERE / "adjudication/mechanisms"


def clip(text: str, head: int = 1400, tail: int = 600) -> str:
    text = (text or "").strip("\n")
    lines = text.splitlines()
    if len(lines) <= 60 and len(text) <= head + tail:
        return text
    return "\n".join(lines[:45]) + "\n...\n" + "\n".join(lines[-20:])


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--rows-per-batch", type=int, default=36)
    args = ap.parse_args()

    known = {r["id"] for r in csv.DictReader((HERE / "labels_safe.csv").open())}
    core = [json.loads(x) for x in (OUT / "transitions_core_v0.3_draft.jsonl").open() if x.strip()]
    rows = [r for r in core if r["label"] == "Y" and r["id"] not in known]
    rows.sort(key=lambda r: (r["split"], r["repo_key"], r["id"]))

    DEST.mkdir(parents=True, exist_ok=True)
    batches = []
    for i in range(0, len(rows), args.rows_per_batch):
        chunk = rows[i:i + args.rows_per_batch]
        name = f"batch_{len(batches) + 1:02d}.jsonl"
        with (DEST / name).open("w") as f:
            for r in chunk:
                f.write(json.dumps({
                    "id": r["id"],
                    "source": r["source"],
                    "repo": r["repo_key"],
                    "path": r.get("path"),
                    "api_old": r.get("api_guess") or r.get("api_old"),
                    "old_snippet": clip(r["old_snippet"]),
                    "new_snippet": clip(r["safe_snippet"]),
                }, ensure_ascii=False) + "\n")
        batches.append({"file": name, "rows": len(chunk),
                        "by_split": dict(Counter(r["split"] for r in chunk))})
    queue = {
        "rows": len(rows),
        "batches": batches,
        "by_source": dict(Counter(r["source"] for r in rows).most_common()),
        "by_split": dict(Counter(r["split"] for r in rows).most_common()),
    }
    (DEST / "queue.json").write_text(json.dumps(queue, indent=2) + "\n")
    print(json.dumps(queue, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
