"""Source-stratified repository split that targets row proportions."""

from __future__ import annotations

from collections import Counter, defaultdict


def assign_splits(rows):
    by_source = defaultdict(list)
    for r in rows:
        by_source[r.get("source", "cvefixes")].append(r.get("repo_name", "unknown"))
    test, valid = set(), set()
    for _, src_rows in sorted(by_source.items()):
        counts = Counter(src_rows)
        total = sum(counts.values())
        ordered = sorted(counts, key=lambda x: (-counts[x], x))
        cum = 0
        for repo in ordered:
            if cum < total * 0.5:
                cum += counts[repo]
            elif cum < total * 0.7:
                valid.add(repo)
                cum += counts[repo]
            else:
                test.add(repo)
    return test, valid
