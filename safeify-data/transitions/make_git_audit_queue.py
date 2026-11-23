"""Audit queue for git-history transitions (out/git_history_pairs.jsonl).

Deduplicates against the mechanism datasets and the version pairs, caps rows
per repository so a handful of large histories cannot dominate, stratifies the
sample by the rule labeller's guess and writes batches under
`adjudication/git_audit/`.
"""

from __future__ import annotations

import argparse
import json
import random
import re
from collections import Counter, defaultdict
from pathlib import Path

from mechanism_rules import predict

HERE = Path(__file__).resolve().parent
OUT = HERE / "out"
DEFAULT_DEST = HERE / "adjudication/git_audit"


def norm(text: str) -> str:
    return re.sub(r"\s+", " ", text or "").strip()


def clip(text: str, head: int = 1400, tail: int = 600) -> str:
    lines = (text or "").strip("\n").splitlines()
    if len(lines) <= 60 and len(text) <= head + tail:
        return text
    return "\n".join(lines[:45]) + "\n...\n" + "\n".join(lines[-20:])


def known_snippets() -> set[str]:
    known: set[str] = set()
    for name in ("mechanism_dataset_plus.jsonl", "version_pairs.jsonl"):
        path = OUT / name
        if path.exists():
            known |= {norm(json.loads(x)["old_snippet"]) for x in path.open() if x.strip()}
    return known


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--sample", type=int, default=240)
    ap.add_argument("--per-repo", type=int, default=4)
    ap.add_argument("--seed", type=int, default=11)
    ap.add_argument("--rows-per-batch", type=int, default=40)
    ap.add_argument("--dest", default="adjudication/git_audit")
    args = ap.parse_args()
    DEST = HERE / args.dest

    mined = [json.loads(x) for x in (OUT / "git_history_pairs.jsonl").open() if x.strip()]
    known = known_snippets()
    seen: set[str] = set()
    cands = []
    for r in mined:
        key = norm(r["old_snippet"])
        if not key or key in known or key in seen:
            continue
        seen.add(key)
        r["rule_guess"] = predict(r["old_snippet"], r["safe_snippet"], r.get("api_old"))
        cands.append(r)

    by_repo = defaultdict(list)
    for r in cands:
        by_repo[r["repo_name"]].append(r)
    rng = random.Random(args.seed)
    capped = []
    for repo, rs in sorted(by_repo.items()):
        rng.shuffle(rs)
        capped.extend(rs[: args.per_repo])
    grouped = defaultdict(list)
    for r in capped:
        grouped[r["rule_guess"] or "no_rule"].append(r)
    quota = max(1, args.sample // max(1, len(grouped)))
    picked, leftover = [], []
    for stratum, rs in sorted(grouped.items(), key=lambda kv: -len(kv[1])):
        rng.shuffle(rs)
        picked.extend(rs[:quota])
        leftover.extend(rs[quota:])
    if len(picked) < args.sample:
        rng.shuffle(leftover)
        picked.extend(leftover[: args.sample - len(picked)])
    picked = picked[: args.sample]
    picked.sort(key=lambda r: (r["repo_name"], r["commit"] or "", r["path"] or ""))

    DEST.mkdir(parents=True, exist_ok=True)
    batches = []
    for i in range(0, len(picked), args.rows_per_batch):
        chunk = picked[i:i + args.rows_per_batch]
        name = f"batch_{len(batches) + 1:02d}.jsonl"
        with (DEST / name).open("w") as f:
            for r in chunk:
                f.write(json.dumps({
                    "id": r["id"],
                    "package": r["repo_name"],
                    "path": r["path"],
                    "api_old": r.get("api_old"),
                    "rule_guess": r["rule_guess"],
                    "old_snippet": clip(r["old_snippet"]),
                    "new_snippet": clip(r["safe_snippet"]),
                }, ensure_ascii=False) + "\n")
        batches.append({"file": name, "rows": len(chunk)})
    queue = {
        "mined_rows": len(mined),
        "unique_new": len(cands),
        "capped": len(capped),
        "sampled": len(picked),
        "strata": dict(Counter(r["rule_guess"] or "no_rule" for r in picked).most_common()),
        "repos": len({r["repo_name"] for r in picked}),
        "batches": batches,
    }
    (DEST / "queue.json").write_text(json.dumps(queue, indent=2) + "\n")
    print(json.dumps(queue, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
