"""Build the v0.3 transition core draft: frozen v0.2 rows + audited expansion.

The v0.2 rows and the frozen valid/test lists are untouched. Audited expansion
rows that belong to frozen train repositories are added to train; rows from
repositories not yet in any split are also seeded into train (their repositories
become training repositories, which keeps the frozen valid/test sets comparable).
U rows are dropped; Y maps to target 1, M/N to target 0.

Writes out/transitions_core_v0.3_draft.jsonl and a stats/leakage report.
"""

from __future__ import annotations

import json
from collections import Counter
from pathlib import Path

from check_split_leakage import audit

HERE = Path(__file__).resolve().parent
OUT = HERE / "out"
VERSION = "v0.3"
LABELED = HERE / "adjudication/expansion/labeled.jsonl"
MAX_NEG_PER_REPO = 20  # ponytail: flat repo cap, tune only if a repo's rows stop being independent


def cap_negatives(rows: list[dict]) -> tuple[list[dict], Counter]:
    """Keep every positive; cap negatives per repository so one repo cannot dominate."""
    kept, dropped = [], Counter()
    per_repo = Counter()
    for r in sorted(rows, key=lambda x: (x["repo_key"], x["id"])):
        if r["replaceability"] in ("Y", "M"):
            kept.append(r)
            continue
        per_repo[r["repo_key"]] += 1
        if per_repo[r["repo_key"]] <= MAX_NEG_PER_REPO:
            kept.append(r)
        else:
            dropped["repo_cap"] += 1
    return kept, dropped


def main() -> int:
    core = [json.loads(x) for x in (OUT / "transitions_core_v0.2.jsonl").open() if x.strip()]
    labels = [json.loads(x) for x in LABELED.open() if x.strip()]

    new_rows = []
    dropped = Counter()
    test_repos = {x["repo_key"] for x in core if x["split"] == "test"}
    valid_repos = {x["repo_key"] for x in core if x["split"] == "valid"}
    eligible = []
    for r in labels:
        if r["replaceability"] == "U":
            dropped["unusable"] += 1
        elif r["repo_key"] in test_repos:
            dropped["belongs_to_sealed_test"] += 1
        elif r["repo_key"] in valid_repos:
            dropped["belongs_to_frozen_valid"] += 1
        else:
            eligible.append(r)
    capped, capped_dropped = cap_negatives(eligible)
    dropped.update(capped_dropped)
    for r in capped:
        row = dict(r)
        row["label"] = r["replaceability"]
        row["target"] = 1 if r["replaceability"] == "Y" else 0
        row["split"] = "train"
        row["dataset_version"] = f"{VERSION}-draft"
        row["frozen"] = False
        row["expansion"] = True
        new_rows.append(row)

    rows = core + new_rows
    leak = audit(rows)
    by_split = Counter(r["split"] for r in rows)
    by_label = Counter(r["label"] for r in rows)
    stats = {
        "dataset_version": f"{VERSION}-draft",
        "frozen": False,
        "rows": len(rows),
        "added": len(new_rows),
        "dropped": dict(dropped),
        "by_split": dict(by_split),
        "by_label": dict(by_label),
        "by_split_label": {f"{s}:{l}": c for (s, l), c in
                           Counter((r["split"], r["label"]) for r in rows).most_common()},
        "positives": sum(1 for r in rows if r["label"] == "Y"),
        "expansion_positives": sum(1 for r in new_rows if r["label"] == "Y"),
        "repos": len({r["repo_key"] for r in rows}),
        "train_repos": len({r["repo_key"] for r in rows if r["split"] == "train"}),
        "split_leakage": {
            "cross_split_snippet_groups": leak["cross_split_snippet_groups"],
            "cross_split_rows": leak["cross_split_rows"],
            "unresolved_repo_keys": leak["unresolved_repo_keys"],
            "pairwise_overlap": leak["pairwise_overlap"],
        },
    }
    assert leak["cross_split_snippet_groups"] == 0, "cross-split duplicate snippets"
    with (OUT / f"transitions_core_{VERSION}_draft.jsonl").open("w") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    (OUT / f"transitions_core_{VERSION}_stats.json").write_text(json.dumps(stats, indent=2) + "\n")
    print(json.dumps(stats, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
