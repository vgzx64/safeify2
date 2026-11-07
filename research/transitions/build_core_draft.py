"""Build an unfrozen transitions-core draft and repository-level splits.

This is a draft, not a release. Positive rows come from the reconciled manual +
LLM union; negative rows come from reviewed M/N labels. Splits are by repository
only (no repository appears in two splits).
"""

from __future__ import annotations

import argparse
import json
from collections import Counter, defaultdict

from split_utils import assign_splits
from pathlib import Path

OUT = Path(__file__).resolve().parent / "out"


def norm(s: str) -> str:
    return "\n".join(" ".join(x.split()) for x in s.splitlines() if x.strip())


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--positives", type=Path, default=OUT / "positive_union.jsonl")
    ap.add_argument("--negatives", type=Path, default=OUT / "negative_core.jsonl")
    ap.add_argument("--out", type=Path, default=OUT / "transitions_core_draft.jsonl")
    ap.add_argument("--splits", type=Path, default=OUT / "splits_draft.json")
    args = ap.parse_args()

    positives = [json.loads(x) for x in args.positives.open()]
    negatives = [json.loads(x) for x in args.negatives.open()]
    rows = []
    seen = set()
    for r in positives:
        r = dict(r)
        r["label"] = "Y"
        r["label_source"] = r.get("positive_source", "manual")
        key = (r.get("repo_name", ""), r.get("path", ""), norm(r.get("old_snippet", "")))
        if key in seen:
            continue
        seen.add(key)
        rows.append(r)
    for r in negatives:
        r = dict(r)
        r["label"] = "N" if r.get("replaceability") == "N" else "M"
        r["label_source"] = "llm"
        key = (r.get("repo_name", ""), r.get("path", ""), norm(r.get("old_snippet", "")))
        if key in seen:
            continue
        seen.add(key)
        rows.append(r)

    repos = sorted({r.get("repo_name", "unknown") for r in rows})
    # 70/10/20 by sorted repository; keep every row of a repository together.
    n = len(repos)
    n_test = max(1, round(n * 0.3))
    n_valid = max(1, round(n * 0.2))
    test = set(repos[:n_test])
    valid = set(repos[n_test:n_test + n_valid])
    for r in rows:
        repo = r.get("repo_name", "unknown")
        r["split"] = "test" if repo in test else "valid" if repo in valid else "train"
        r["dataset_version"] = "draft-v0"
        r["frozen"] = False

    with args.out.open("w") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    splits = {
        "seed": 1234,
        "strategy": "source-stratified repository split, 50/20/30 train/valid/test",
        "test_repos": sorted(test),
        "valid_repos": sorted(valid),
        "train_repos": sorted(set(repos) - test - valid),
    }
    args.splits.write_text(json.dumps(splits, indent=2) + "\n")
    stats = {
        "rows": len(rows),
        "by_split": dict(Counter(r["split"] for r in rows)),
        "by_label": dict(Counter(r["label"] for r in rows)),
        "by_split_label": {f"{s}:{l}": c for (s, l), c in Counter((r["split"], r["label"]) for r in rows).items()},
        "repos": len(repos),
    }
    (OUT / "transitions_core_draft_stats.json").write_text(json.dumps(stats, indent=2) + "\n")
    print(json.dumps(stats, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
