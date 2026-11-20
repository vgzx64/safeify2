"""Build the gate-closing adjudication batches.

Batch A: 161 unreviewed CVEfixes queue rows, one per remaining family first,
then second rows, to lift queue coverage from 206/458 to 367/458 (80.1%).

Batch B: 140 unreviewed crates.io / RustSec retained rows, one per family that
no reviewed row has touched yet, to add new hard-negative families.

Rows are written as self-contained chunk files (snippets included); each chunk is
handed to one adjudicator. No source pool file is modified.
"""

from __future__ import annotations

import argparse
import json
import random
from collections import Counter, defaultdict
from pathlib import Path

HERE = Path(__file__).resolve().parent
OUT = HERE.parent / "out"
SEED = 20261107


def load(path: Path) -> list[dict]:
    return [json.loads(x) for x in path.open() if x.strip()]


def family(r: dict) -> tuple[str, str, str]:
    repo = r.get("repo_name") or r.get("package") or "unknown"
    return (repo, r.get("path", ""), r.get("fn_id") or "")


def repo_of(r: dict) -> str:
    return r.get("repo_name") or r.get("package") or "unknown"


def usable(r: dict) -> bool:
    return bool(r.get("old_snippet", "").strip()) and bool(r.get("safe_snippet", "").strip())


def one_per_family(rows: list[dict], rng: random.Random) -> list[dict]:
    """Pick one row per family, spreading families across repositories."""
    by_fam: dict[tuple, list[dict]] = defaultdict(list)
    for r in rows:
        by_fam[family(r)].append(r)
    for fam_rows in by_fam.values():
        fam_rows.sort(key=lambda r: (r.get("span_start") or 0, r.get("id", "")))
    fams = list(by_fam)
    rng.shuffle(fams)
    # round-robin across repositories so no single repo dominates the first pass
    by_repo: dict[str, list[tuple]] = defaultdict(list)
    for f in fams:
        by_repo[f[0]].append(f)
    for repo_fams in by_repo.values():
        rng.shuffle(repo_fams)
    picked: list[dict] = []
    repos = list(by_repo)
    rng.shuffle(repos)
    while any(by_repo[r] for r in repos):
        for repo in repos:
            if by_repo[repo]:
                picked.append(by_fam[by_repo[repo].pop()][0])
    return picked


def chunk(rows: list[dict], n: int) -> list[list[dict]]:
    """Split rows into n contiguous chunks of roughly equal size."""
    size = len(rows) // n
    extra = len(rows) % n
    out, start = [], 0
    for i in range(n):
        take = size + (1 if i < extra else 0)
        out.append(rows[start:start + take])
        start += take
    return out


def write_rows(path: Path, rows: list[dict]) -> None:
    with path.open("w") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--queue-rows", type=int, default=161)
    ap.add_argument("--expansion-rows", type=int, default=140)
    ap.add_argument("--queue-chunks", type=int, default=6)
    ap.add_argument("--expansion-chunks", type=int, default=5)
    ap.add_argument("--only-b", action="store_true", help="rebuild expansion chunks without touching batch A")
    args = ap.parse_args()

    rng = random.Random(SEED)
    reviewed = load(HERE / "reviewed_all.jsonl")
    reviewed_ids = {r.get("queue_id") or r.get("id") for r in reviewed}
    reviewed_fams = {family(r) for r in reviewed}

    a_rows: list[dict] = []
    if not args.only_b:
        queue = [r for r in load(HERE / "queue.jsonl") if usable(r)]
        queue = [r for r in queue if (r.get("queue_id") or r.get("id")) not in reviewed_ids]
        # Batch A: one row per remaining family, then extra rows for coverage.
        fam_pick = one_per_family(queue, rng)
        a_rows = list(fam_pick)
        chosen = {r["id"] for r in a_rows}
        rest = [r for r in queue if r["id"] not in chosen]
        rng.shuffle(rest)
        a_rows.extend(rest[: max(0, args.queue_rows - len(a_rows))])
        a_rows = a_rows[: args.queue_rows]
        assert len(a_rows) == args.queue_rows, len(a_rows)

    # Batch B: untouched expansion families, one row per family.
    expansion = []
    for name in ("cratesio_candidates.jsonl", "rustsec_hunks.jsonl",
                 "rustsec_issue_hunks.jsonl", "rust_for_linux_hunks.jsonl"):
        for r in load(OUT / name):
            if r.get("kind") != "unsafe_retained" or not usable(r):
                continue
            key = r.get("queue_id") or r.get("id")
            if key in reviewed_ids or family(r) in reviewed_fams:
                continue
            expansion.append(r)
    assert len(expansion) > args.expansion_rows
    b_rows = one_per_family(expansion, rng)[: args.expansion_rows]
    assert len(b_rows) == args.expansion_rows

    for group in ([g for g in (a_rows, b_rows) if g]):
        for r in group:
            r["queue_id"] = r.get("queue_id") or r["id"]
            r["repo_name"] = repo_of(r)
            r["batch_family"] = "|".join(family(r))
            r.setdefault("review_status", "unreviewed")

    manifest = {"seed": SEED, "a_rows": len(a_rows), "b_rows": len(b_rows),
                "a_families": len({family(r) for r in a_rows}),
                "b_families": len({family(r) for r in b_rows}),
                "a_repos": len({repo_of(r) for r in a_rows}),
                "b_repos": len({repo_of(r) for r in b_rows})}
    for tag, rows, n_chunks in (("a", a_rows, args.queue_chunks),
                                ("b", b_rows, args.expansion_chunks)):
        if not rows:
            continue
        for i, part in enumerate(chunk(rows, n_chunks), 1):
            name = f"gate_{tag}{i:02d}"
            write_rows(HERE / f"{name}.jsonl", part)
            manifest[name] = len(part)
    (HERE / "gate_batches.json").write_text(json.dumps(manifest, indent=2) + "\n")
    print(json.dumps(manifest, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
