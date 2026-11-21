"""Build the v0.3 expansion audit queue.

Takes the draft expansion pool, keeps the rows that can enter training (rows of
frozen train repositories plus rows from repositories not yet in any split),
drops rows that are undecidable by construction (empty old or new snippet), and
writes small JSONL batches with clipped snippets for LLM adjudication under
`adjudication/RUBRIC.md`.
"""

from __future__ import annotations

import argparse
import json
import re
from collections import Counter
from pathlib import Path

HERE = Path(__file__).resolve().parent
OUT = HERE / "out"
DEST = HERE / "adjudication/expansion"
UNSAFE = re.compile(
    r"\bunsafe\s*(?:\{|fn\b|impl\b|trait\b)"
    r"|\b(?:pointer|ptr)::(?:read|write|copy|copy_nonoverlapping)\b"
    r"|\b(?:Box|Vec|CString|CStr|Rc|Arc)::from_raw(?:_parts)?\b"
    r"|\bset_len\s*\(|\bassume_init\b|\btransmute|\bget_unchecked\b"
    r"|\boffset_from\b|\bPin::new_unchecked\b|\bzeroed\s*\("
    r"|\buninitialized\s*\(",
)


def clip(text: str, head: int = 1400, tail: int = 600) -> str:
    """Keep the start and end of a snippet, which is where the change lives."""
    text = (text or "").strip("\n")
    lines = text.splitlines()
    if len(lines) <= 60 and len(text) <= head + tail:
        return text
    return "\n".join(lines[:45]) + "\n...\n" + "\n".join(lines[-20:])


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--rows-per-batch", type=int, default=48)
    args = ap.parse_args()

    pool = [json.loads(x) for x in (OUT / "expansion_pool_draft.jsonl").open() if x.strip()]
    keep, dropped = [], Counter()
    for r in pool:
        if r["split"] not in ("train", "unassigned"):
            dropped["other_split"] += 1
            continue
        if not (r.get("old_snippet") or "").strip():
            dropped["empty_old"] += 1
            continue
        if not (r.get("safe_snippet") or "").strip():
            dropped["empty_new"] += 1
            continue
        keep.append(r)

    keep.sort(key=lambda r: (r["split"] != "unassigned", r["source"], r["kind"], r["id"]))
    DEST.mkdir(parents=True, exist_ok=True)
    batches = []
    for i in range(0, len(keep), args.rows_per_batch):
        chunk = keep[i:i + args.rows_per_batch]
        name = f"batch_{len(batches) + 1:02d}.jsonl"
        with (DEST / name).open("w") as f:
            for r in chunk:
                out = {
                    "id": r["id"],
                    "source": r["source"],
                    "kind": r["kind"],
                    "repo": r["repo_key"],
                    "path": r.get("path"),
                    "api_old": r.get("api_old"),
                    "api_new": r.get("api_new"),
                    "old_snippet": clip(r["old_snippet"]),
                    "new_snippet": clip(r["safe_snippet"]),
                }
                f.write(json.dumps(out, ensure_ascii=False) + "\n")
        batches.append({"file": name, "rows": len(chunk),
                        "by_kind": dict(Counter(r["kind"] for r in chunk)),
                        "by_source": dict(Counter(r["source"] for r in chunk))})
    queue = {
        "rows": len(keep),
        "batches": batches,
        "dropped": dict(dropped),
        "by_split": dict(Counter(r["split"] for r in keep)),
        "by_kind": dict(Counter(r["kind"] for r in keep)),
        "y_candidates_with_unsafe_in_new": sum(
            1 for r in keep if r["kind"] == "safe_candidate"
            and UNSAFE.search(r["safe_snippet"])),
    }
    (DEST / "queue.json").write_text(json.dumps(queue, indent=2) + "\n")
    print(json.dumps(queue, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
