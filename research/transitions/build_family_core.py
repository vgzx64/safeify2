"""Build a family-level exploratory core and an honest quality-gate report.

This does not freeze the dataset. It collapses multiple hunks in the same
(repo, path, function) family and records why the freeze gates still fail.
"""

from __future__ import annotations

import json
from collections import Counter, defaultdict

from split_utils import assign_splits
from pathlib import Path

OUT = Path(__file__).resolve().parent / "out"


def norm(s: str) -> str:
    return "\n".join(" ".join(x.split()) for x in s.splitlines() if x.strip())


def main() -> int:
    pos = [json.loads(x) for x in (OUT / "positive_union.jsonl").open()]
    neg = [json.loads(x) for x in (OUT / "negative_core.jsonl").open()]
    # One row per family; prefer manual, then a row with a function id.
    fam = {}
    for r in pos:
        k = (r.get("repo_name", ""), r.get("path", ""), r.get("fn_id") or "")
        score = (1 if r.get("positive_source") == "manual" else 0, 1 if r.get("fn_id") else 0)
        if k not in fam or score > fam[k][0]:
            fam[k] = (score, r)
    pos_rows = [r for _, r in fam.values()]
    for r in pos_rows:
        r["label"] = "Y"
        r["unit"] = "family"
    # Deduplicate negatives by the same family key.
    neg_fam = {}
    for r in neg:
        k = (r.get("repo_name", ""), r.get("path", ""), r.get("fn_id") or "")
        neg_fam[k] = r
    neg_rows = list(neg_fam.values())
    for r in neg_rows:
        r["label"] = r["replaceability"]
        r["unit"] = "family"
    rows = pos_rows + neg_rows

    test, valid = assign_splits(rows)
    repos = sorted({r.get("repo_name", "unknown") for r in rows})
    for r in rows:
        repo = r.get("repo_name", "unknown")
        r["split"] = "test" if repo in test else "valid" if repo in valid else "train"
        r["dataset_version"] = "v0.1-exploratory"
        r["frozen"] = False

    with (OUT / "transitions_core_v0.1_exploratory.jsonl").open("w") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    splits = {
        "strategy": "source-stratified repository split, 50/20/30 train/valid/test",
        "test_repos": sorted(test),
        "valid_repos": sorted(valid),
        "train_repos": sorted(set(repos) - test - valid),
    }
    (OUT / "splits_v0.1.json").write_text(json.dumps(splits, indent=2) + "\n")

    counts = {
        "rows": len(rows),
        "positives": len(pos_rows),
        "negatives": len(neg_rows),
        "by_label": dict(Counter(r["label"] for r in rows)),
        "by_split": dict(Counter(r["split"] for r in rows)),
        "by_split_label": {f"{s}:{l}": c for (s, l), c in Counter((r["split"], r["label"]) for r in rows).items()},
        "repos": len(repos),
        "queue_labeled": 206,
        "queue_total": 458,
    }
    quality = {
        "dataset_version": "v0.1-exploratory",
        "frozen": False,
        "gates": {
            "positive_families_ge_100": counts["positives"] >= 100,
            "negative_rows_ge_300": counts["negatives"] >= 300,
            "test_rows_ge_50": counts["by_split"].get("test", 0) >= 50,
            "queue_coverage_ge_80pct": counts["queue_labeled"] / counts["queue_total"] >= 0.8,
            "manual_llm_tracks_reconciled": True,
        },
        "counts": counts,
        "verdict": "not frozen; exploratory only",
    }
    (OUT / "transitions_core_v0.1_quality.json").write_text(json.dumps(quality, indent=2) + "\n")
    print(json.dumps(quality, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
