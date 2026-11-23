"""Build the audit queue for version-history pairs (route C).

Mined pairs are objective old->new transitions with no labels at all. This
script deduplicates them against the existing corpus, caps per package so one
crate cannot dominate, stratifies the sample by the rule labeller's guess (to
keep mechanism coverage) and writes small batches for adjudication: verdict
(Y/M/N/U) plus mechanism for Y rows.
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
DEST = HERE / "adjudication/version_audit"


def norm(text: str) -> str:
    return re.sub(r"\s+", " ", text or "").strip()


def clip(text: str, head: int = 1400, tail: int = 600) -> str:
    lines = (text or "").strip("\n").splitlines()
    if len(lines) <= 60 and len(text) <= head + tail:
        return text
    return "\n".join(lines[:45]) + "\n...\n" + "\n".join(lines[-20:])


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--sample", type=int, default=240)
    ap.add_argument("--per-package", type=int, default=12)
    ap.add_argument("--seed", type=int, default=7)
    ap.add_argument("--rows-per-batch", type=int, default=40)
    args = ap.parse_args()

    mined = [json.loads(x) for x in (OUT / "version_pairs.jsonl").open() if x.strip()]
    corpus = [json.loads(x) for x in (OUT / "mechanism_dataset.jsonl").open() if x.strip()]
    known = {norm(r["old_snippet"]) for r in corpus}

    seen: set[str] = set()
    cands = []
    for r in mined:
        key = norm(r["old_snippet"])
        if not key or key in known or key in seen:
            continue
        seen.add(key)
        r["rule_guess"] = predict(r["old_snippet"], r["safe_snippet"], r.get("api_old"))
        cands.append(r)

    # cap per package, then stratify by rule guess
    by_pkg = defaultdict(list)
    for r in cands:
        by_pkg[r["package"]].append(r)
    rng = random.Random(args.seed)
    capped = []
    for pkg, rs in sorted(by_pkg.items()):
        rng.shuffle(rs)
        capped.extend(rs[: args.per_package])
    grouped = defaultdict(list)
    for r in capped:
        grouped[r["rule_guess"] or "no_rule"].append(r)
    picked = []
    # equal quota per stratum, remainder from the leftover pool
    quota = max(1, args.sample // max(1, len(grouped)))
    leftover = []
    for stratum, rs in sorted(grouped.items(), key=lambda kv: -len(kv[1])):
        rng.shuffle(rs)
        picked.extend(rs[:quota])
        leftover.extend(rs[quota:])
    if len(picked) < args.sample:
        rng.shuffle(leftover)
        picked.extend(leftover[: args.sample - len(picked)])
    picked = picked[: args.sample]
    picked.sort(key=lambda r: (r["package"], r["version_before"], r["path"], r["old_snippet"]))

    DEST.mkdir(parents=True, exist_ok=True)
    batches = []
    for i in range(0, len(picked), args.rows_per_batch):
        chunk = picked[i:i + args.rows_per_batch]
        name = f"batch_{len(batches) + 1:02d}.jsonl"
        with (DEST / name).open("w") as f:
            for r in chunk:
                f.write(json.dumps({
                    "id": r["id"],
                    "package": r["package"],
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
        "packages": len({r["package"] for r in picked}),
        "batches": batches,
    }
    (DEST / "queue.json").write_text(json.dumps(queue, indent=2) + "\n")
    print(json.dumps(queue, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
