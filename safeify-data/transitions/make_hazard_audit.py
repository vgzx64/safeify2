"""Apply the hazard taxonomy to the corpus and build a blind audit sample.

Writes:
  out/hazard_labels.jsonl   every row with rule-assigned hazard + matched pattern
  adjudication/hazard/sample.jsonl   blind 60-row sample for two annotators
  adjudication/hazard/queue.json     sampling stats
"""

from __future__ import annotations

import argparse
import json
import random
from collections import Counter
from pathlib import Path

from hazard_taxonomy import HAZARDS, classify

HERE = Path(__file__).resolve().parent
OUT = HERE / "out"
DEST = HERE / "adjudication/hazard"


def clip(text: str, head: int = 1400, tail: int = 600) -> str:
    lines = (text or "").strip("\n").splitlines()
    if len(lines) <= 60 and len(text) <= head + tail:
        return text
    return "\n".join(lines[:45]) + "\n...\n" + "\n".join(lines[-20:])


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--sample", type=int, default=60)
    ap.add_argument("--seed", type=int, default=31)
    args = ap.parse_args()

    rows = [json.loads(x) for x in (OUT / "mechanism_dataset_v05.jsonl").open() if x.strip()]
    labelled = []
    for r in rows:
        hazard, pattern = classify(r["old_snippet"])
        labelled.append({
            "id": r["id"],
            "split": r["split"],
            "repo_key": r["repo_key"],
            "hazard": hazard,
            "pattern": pattern,
            "old_snippet": r["old_snippet"],
        })
    with (OUT / "hazard_labels.jsonl").open("w") as f:
        for r in labelled:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")

    by_split = {s: dict(Counter(r["hazard"] for r in labelled if r["split"] == s).most_common())
                for s in ("train", "valid", "test")}
    unknown_share = sum(1 for r in labelled if r["hazard"] == "unknown") / len(labelled)

    train = [r for r in labelled if r["split"] == "train"]
    rng = random.Random(args.seed)
    grouped = {}
    for r in train:
        grouped.setdefault(r["hazard"], []).append(r)
    per_class = max(1, args.sample // len(grouped))
    sample = []
    for hazard, rs in grouped.items():
        rng.shuffle(rs)
        sample.extend(rs[:per_class])
    rng.shuffle(sample)
    sample = sample[: args.sample]

    DEST.mkdir(parents=True, exist_ok=True)
    with (DEST / "sample.jsonl").open("w") as f:
        for r in sample:
            f.write(json.dumps({
                "id": r["id"],
                "repo": r["repo_key"],
                "old_snippet": clip(r["old_snippet"]),
            }, ensure_ascii=False) + "\n")
    queue = {
        "rows": len(labelled),
        "unknown_share": round(unknown_share, 3),
        "by_split": by_split,
        "sample": len(sample),
        "sample_by_hazard": dict(Counter(r["hazard"] for r in sample).most_common()),
    }
    (DEST / "queue.json").write_text(json.dumps(queue, indent=2) + "\n")
    print(json.dumps({k: queue[k] for k in ("rows", "unknown_share", "sample",
                                            "sample_by_hazard")}, indent=2))
    print("train hazards:", by_split["train"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
