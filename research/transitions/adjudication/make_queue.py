"""Build the full LLM adjudication queue and a stratified pilot batch."""

from __future__ import annotations

import argparse
import json
import random
from collections import Counter, defaultdict
from pathlib import Path

OUT = Path(__file__).resolve().parent.parent / "out"
HERE = Path(__file__).resolve().parent


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--pilot", type=int, default=60)
    ap.add_argument("--name", default="pilot_001")
    args = ap.parse_args()
    rows = [json.loads(x) for x in (OUT / "all_hunks.jsonl").open()]
    queue = []
    for r in rows:
        if r["kind"] not in ("safe_candidate", "unsafe_retained"):
            continue
        if not r.get("old_snippet", "").strip() or not r.get("safe_snippet", "").strip():
            continue
        r = dict(r)
        r["queue_id"] = r["id"]
        queue.append(r)
    with (HERE / "queue.jsonl").open("w") as f:
        for r in queue:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")

    rng = random.Random(7)
    by_kind = defaultdict(list)
    for r in queue:
        by_kind[r["kind"]].append(r)
    pilot = []
    for kind, n in (("safe_candidate", args.pilot * 2 // 3),
                    ("unsafe_retained", args.pilot - args.pilot * 2 // 3)):
        pool = sorted(by_kind[kind], key=lambda r: (r["repo_name"], r["path"], r["span_start"]))
        rng.shuffle(pool)
        used = Counter()
        for r in pool:
            if used[r["repo_name"]] >= 3:
                continue
            pilot.append(r)
            used[r["repo_name"]] += 1
            if sum(1 for x in pilot if x["kind"] == kind) >= n:
                break
    with (HERE / f"{args.name}.jsonl").open("w") as f:
        for r in pilot:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    stats = {
        "queue": len(queue),
        "queue_kinds": dict(Counter(r["kind"] for r in queue)),
        "pilot": len(pilot),
        "pilot_kinds": dict(Counter(r["kind"] for r in pilot)),
        "pilot_repos": len(set(r["repo_name"] for r in pilot)),
    }
    (HERE / "queue_stats.json").write_text(json.dumps(stats, indent=2) + "\n")
    print(json.dumps(stats, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
