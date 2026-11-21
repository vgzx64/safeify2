"""Build the v0.3 expansion pool from already-extracted, unreviewed candidates.

The three extractors plus the crates.io miner already wrote every candidate row
they could find; the v0.2 core used only a reviewed subset. This script takes
the untouched rows, deduplicates them against the frozen core and against each
other, resolves repository identity, and assigns each row to the frozen split
of its repository (rows from new repositories stay `unassigned` until labels
are known). It writes a draft pool only; no labels are invented here.
"""

from __future__ import annotations

import json
import re
from collections import Counter
from pathlib import Path

from repo_identity import annotate

HERE = Path(__file__).resolve().parent
OUT = HERE / "out"
SOURCES = [
    "all_hunks.jsonl",
    "rustsec_hunks.jsonl",
    "rustsec_issue_hunks.jsonl",
    "rust_for_linux_hunks.jsonl",
    "cratesio_candidates.jsonl",
]
PRIORITY = {"cvefixes": 0, "rustsec": 1, "rust-for-linux": 2, "cratesio": 3}


def load(path: Path) -> list[dict]:
    return [json.loads(x) for x in path.open() if x.strip()]


def norm(text: str) -> str:
    return re.sub(r"\s+", " ", text or "").strip()


def main() -> int:
    reviewed = {
        r.get("queue_id") or r.get("id")
        for r in load(HERE / "adjudication/reviewed_all.jsonl")
    }
    core = load(OUT / "transitions_core_v0.2.jsonl")
    core_ids = {r["id"] for r in core}
    core_snips = {norm(r["old_snippet"]) for r in core}

    pool: list[dict] = []
    for name in SOURCES:
        for r in load(OUT / name):
            if (r.get("queue_id") or r["id"]) in reviewed or r["id"] in core_ids:
                continue
            pool.append(r)

    pool.sort(key=lambda r: (PRIORITY[r["source"]], -len(r["safe_snippet"] or ""), r["id"]))
    seen: set[str] = set()
    uniq = []
    for r in pool:
        key = norm(r["old_snippet"])
        if not key or key in core_snips or key in seen:
            continue
        seen.add(key)
        uniq.append(r)

    annotate(uniq)
    splits = json.loads((OUT / "splits_v0.2.json").read_text())
    where = {**{k: "test" for k in splits["test_repos"]},
             **{k: "valid" for k in splits["valid_repos"]},
             **{k: "train" for k in splits["train_repos"]}}
    for r in uniq:
        r["split"] = where.get(r["repo_key"], "unassigned")

    with (OUT / "expansion_pool_draft.jsonl").open("w") as f:
        for r in uniq:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    stats = {
        "rows": len(uniq),
        "by_source": dict(Counter(r["source"] for r in uniq).most_common()),
        "by_kind": dict(Counter(r["kind"] for r in uniq).most_common()),
        "by_source_kind": {f"{s}/{k}": c for (s, k), c in
                           Counter((r["source"], r["kind"]) for r in uniq).most_common()},
        "by_split": dict(Counter(r["split"] for r in uniq).most_common()),
        "unassigned_repos": sorted({r["repo_key"] for r in uniq if r["split"] == "unassigned"}),
    }
    (OUT / "expansion_pool_stats.json").write_text(json.dumps(stats, indent=2) + "\n")
    print(json.dumps(stats, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
