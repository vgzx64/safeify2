"""Build the mechanism dataset for route C: audited version-history pairs added.

Adds the audited version-history transitions to the v0.3 mechanism dataset.
Y rows carry their audited mechanism; M/N rows are `retain`. Rows from
repositories already in the frozen valid/test sets are dropped so those splits
stay exactly frozen; new repositories join `train` (same rule as v0.3).

Deduplicated by normalised `old_snippet`. Writes
out/mechanism_dataset_plus.jsonl and a stats file.
"""

from __future__ import annotations

import json
import re
from collections import Counter
from pathlib import Path

from mechanism_taxonomy import family

HERE = Path(__file__).resolve().parent
OUT = HERE / "out"


def norm(text: str) -> str:
    return re.sub(r"\s+", " ", text or "").strip()


def main() -> int:
    import argparse
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--audit", default="adjudication/version_audit/labeled.jsonl",
                    help="comma-separated labeled.jsonl files to add")
    ap.add_argument("--out", default="out/mechanism_dataset_plus.jsonl")
    ap.add_argument("--stats", default="out/mechanism_dataset_plus_stats.json")
    args = ap.parse_args()
    base = [json.loads(x) for x in (OUT / "mechanism_dataset.jsonl").open() if x.strip()]
    audit = []
    for path in args.audit.split(","):
        audit.extend(json.loads(x) for x in (HERE / path).open() if x.strip())

    valid_repos = {r["repo_key"] for r in base if r["split"] == "valid"}
    test_repos = {r["repo_key"] for r in base if r["split"] == "test"}
    seen = {norm(r["old_snippet"]) for r in base}
    added, dropped = [], Counter()
    for r in audit:
        key = norm(r["old_snippet"])
        if key in seen:
            dropped["duplicate"] += 1
            continue
        seen.add(key)
        verdict = r["replaceability"]
        if verdict == "U":
            dropped["unusable"] += 1
            continue
        repo = r.get("repo_url") or f"name:{r.get('repo_name', r.get('package', ''))}".lower()
        if repo in test_repos or repo in valid_repos:
            dropped["frozen_repo"] += 1  # keep valid/test exactly frozen
            continue
        split = "train"
        mech = r["mechanism"] if verdict == "Y" else "retain"
        added.append({
            "id": r["id"],
            "split": split,
            "source": r.get("source", "versions"),
            "repo_key": repo,
            "label": verdict,
            "mechanism": mech,
            "family": family(mech),
            "mechanism_source": f"{r.get('source', 'versions')}_audit",
            "api_guess": r.get("api_old") or "unknown",
            "old_snippet": r["old_snippet"],
            "safe_snippet": r["safe_snippet"],
        })

    rows = base + added
    train = [r for r in rows if r["split"] == "train"]
    stats = {
        "base_rows": len(base),
        "audited_rows": len(audit),
        "added": len(added),
        "dropped": dict(dropped),
        "rows": len(rows),
        "by_split": dict(Counter(r["split"] for r in rows).most_common()),
        "by_mechanism_added": dict(Counter(r["mechanism"] for r in added).most_common()),
        "train_y": dict(Counter(r["mechanism"] for r in train
                                if r["mechanism"] != "retain").most_common()),
        "valid_y": dict(Counter(r["mechanism"] for r in rows
                                if r["split"] == "valid" and r["mechanism"] != "retain").most_common()),
    }
    with (HERE / args.out).open("w") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    (HERE / args.stats).write_text(json.dumps(stats, indent=2) + "\n")
    print(json.dumps(stats, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
