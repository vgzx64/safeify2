"""Repository split targeting 50/20/30 rows *and* positives.

Repositories are the unit, so a whole repo never straddles splits. Repos are
processed positive-first and placed in the split with the largest positive
deficit that still has row capacity; zero-positive repos fill the remainder by
row deficit. This keeps both row and label composition close to target without
splitting a repository.
"""

from __future__ import annotations

from collections import Counter

SPLITS = ("train", "valid", "test")


def assign_splits(rows):
    counts = Counter(r.get("repo_key") or r.get("repo_name", "unknown") for r in rows)
    pos = Counter(
        r.get("repo_key") or r.get("repo_name", "unknown")
        for r in rows
        if r.get("label") == "Y"
    )
    total, positives = sum(counts.values()), sum(pos.values()) or 1
    target_rows = {s: f * total for s, f in zip(SPLITS, (0.5, 0.2, 0.3))}
    target_pos = {s: f * positives for s, f in zip(SPLITS, (0.5, 0.2, 0.3))}

    got = dict.fromkeys(SPLITS, 0)
    got_pos = dict.fromkeys(SPLITS, 0)
    where = {}
    for repo in sorted(counts, key=lambda r: (-pos[r], -counts[r], r)):
        fits = [s for s in SPLITS if got[s] + counts[repo] <= target_rows[s]]
        split = max(
            fits or SPLITS,
            key=lambda s: (target_pos[s] - got_pos[s]) / target_pos[s]
            if fits
            else target_rows[s] - got[s],
        )
        where[repo] = split
        got[split] += counts[repo]
        got_pos[split] += pos[repo]

    return (
        {r for r, s in where.items() if s == "test"},
        {r for r, s in where.items() if s == "valid"},
    )
