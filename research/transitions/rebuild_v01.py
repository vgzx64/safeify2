"""Rebuild negative_core, positive_union and the family core after labeling.

negative_core  = every reviewed row labeled N or M (the hard-negative pool).
positive_union = existing manual/LLM positives plus any newly reviewed Y row
                 that is not already present by (repo, path, old snippet).
Then the family core, splits and quality gates are regenerated.
"""

from __future__ import annotations

import json
from pathlib import Path

from build_family_core import main as build_family

HERE = Path(__file__).resolve().parent
OUT = HERE / "out"
ADJ = HERE / "adjudication"


def load(path: Path) -> list[dict]:
    return [json.loads(x) for x in path.open() if x.strip()]


def norm(s: str) -> str:
    return "\n".join(" ".join(x.split()) for x in s.splitlines() if x.strip())


def main() -> int:
    reviewed = load(ADJ / "reviewed_all.jsonl")
    neg = [r for r in reviewed if r.get("replaceability") in ("N", "M")]
    with (OUT / "negative_core.jsonl").open("w") as f:
        for r in neg:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")

    rev_by_id = {r["id"]: r for r in reviewed}
    pos = load(OUT / "positive_union.jsonl")
    # drop LLM positives that a spot-check has since demoted
    pos = [
        r for r in pos
        if r.get("positive_source") == "manual"
        or r["id"] not in rev_by_id
        or rev_by_id[r["id"]].get("replaceability") == "Y"
    ]
    seen = {(r.get("repo_name"), r.get("path"), norm(r.get("old_snippet", ""))) for r in pos}
    added = 0
    npos_ids = {r.get("queue_id") or r.get("id") for r in pos}
    for r in reviewed:
        if r.get("replaceability") != "Y" or r.get("veto"):
            continue
        key = (r.get("repo_name") or r.get("package"), r.get("path"), norm(r.get("old_snippet", "")))
        if key in seen or r["id"] in npos_ids:
            continue
        seen.add(key)
        npos_ids.add(r["id"])
        row = dict(r)
        row["label"] = "Y"
        row["positive_source"] = "llm"
        pos.append(row)
        added += 1
    with (OUT / "positive_union.jsonl").open("w") as f:
        for r in pos:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")

    print(json.dumps({
        "reviewed": len(reviewed),
        "negative_rows": len(neg),
        "negative_labels": {k: sum(1 for r in neg if r.get("replaceability") == k) for k in ("N", "M")},
        "positive_rows": len(pos),
        "positive_added": added,
    }, indent=2))
    return build_family()


if __name__ == "__main__":
    raise SystemExit(main())
