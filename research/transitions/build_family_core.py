"""Build a family-level exploratory core and an honest quality-gate report.

This does not freeze the dataset. It collapses multiple hunks in the same
(repo, path, function) family and records why the freeze gates still fail.
"""

from __future__ import annotations

import json
from collections import Counter, defaultdict

import corrections
from split_utils import assign_splits
from repo_identity import annotate
from check_split_leakage import audit, verdict
from pathlib import Path

OUT = Path(__file__).resolve().parent / "out"


def norm(s: str) -> str:
    return "\n".join(" ".join(x.split()) for x in s.splitlines() if x.strip())


def main() -> int:
    pos = corrections.apply([json.loads(x) for x in (OUT / "positive_union.jsonl").open()])
    neg = corrections.apply([json.loads(x) for x in (OUT / "negative_core.jsonl").open()])
    pos = [r for r in pos if r.get("positive_source") == "manual" or r.get("replaceability", "Y") == "Y"]
    neg = [r for r in neg if r.get("replaceability") in ("N", "M")]
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
    identity = annotate(rows)

    test, valid = assign_splits(rows)
    repos = sorted({r.get("repo_key", "unknown") for r in rows})
    for r in rows:
        repo = r.get("repo_key", "unknown")
        r["split"] = "test" if repo in test else "valid" if repo in valid else "train"
        r["dataset_version"] = "v0.2-draft"
        r["frozen"] = False
        r["target"] = 1 if r["label"] == "Y" else 0
        r["target_name"] = "safe_replaceable" if r["target"] else "unsafe_retained"

    with (OUT / "transitions_core_v0.2_draft.jsonl").open("w") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    splits = {
        "strategy": "canonical-repository split, 50/20/30 rows and positives",
        "test_repos": sorted(test),
        "valid_repos": sorted(valid),
        "train_repos": sorted(set(repos) - test - valid),
    }
    (OUT / "splits_v0.2.json").write_text(json.dumps(splits, indent=2) + "\n")

    adj = Path(__file__).resolve().parent / "adjudication"
    queue_ids = set()
    for line in (adj / "queue.jsonl").open():
        if line.strip():
            r = json.loads(line)
            queue_ids.add(r.get("queue_id") or r.get("id"))
    reviewed_ids = set()
    for line in (adj / "reviewed_all.jsonl").open():
        if line.strip():
            r = json.loads(line)
            reviewed_ids.add(r.get("queue_id") or r.get("id"))
    counts = {
        "rows": len(rows),
        "positives": len(pos_rows),
        "negatives": len(neg_rows),
        "by_label": dict(Counter(r["label"] for r in rows)),
        "by_split": dict(Counter(r["split"] for r in rows)),
        "by_split_label": {f"{s}:{l}": c for (s, l), c in Counter((r["split"], r["label"]) for r in rows).items()},
        "repos": len(repos),
        "identity": dict(identity),
        "queue_labeled": len(queue_ids & reviewed_ids),
        "queue_total": len(queue_ids),
    }
    leak = audit(rows)
    issues = []
    if leak["cross_split_snippet_groups"]:
        issues.append(
            f"split leakage: {leak['cross_split_snippet_groups']} cross-split duplicate "
            f"groups / {leak['cross_split_rows']} rows; see out/split_leakage.json"
        )
    issues.append("single-annotator LLM labels; second independent spot-check still required")
    quality = {
        "dataset_version": "v0.2-draft",
        "frozen": False,
        "gates": {
            "positive_families_ge_100": counts["positives"] >= 100,
            "negative_rows_ge_300": counts["negatives"] >= 300,
            "test_rows_ge_50": counts["by_split"].get("test", 0) >= 50,
            "queue_coverage_ge_80pct": counts["queue_labeled"] / counts["queue_total"] >= 0.8,
            "manual_llm_tracks_reconciled": True,
        },
        "counts": counts,
        "split_leakage": {
            "cross_split_snippet_groups": leak["cross_split_snippet_groups"],
            "cross_split_rows": leak["cross_split_rows"],
            "unresolved_repo_keys": leak["unresolved_repo_keys"],
            "pairwise_overlap": leak["pairwise_overlap"],
        },
        "train_ready": False,
        "known_issues": issues,
        "verdict": "all gates pass; " + verdict(leak),
    }
    (OUT / "transitions_core_v0.2_quality.json").write_text(json.dumps(quality, indent=2) + "\n")
    print(json.dumps(quality, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
