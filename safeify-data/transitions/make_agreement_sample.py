"""Blind sample for classifier-label agreement.

Samples train rows (40 Y + 20 retain by default) and writes the same rows for
two independent annotators. The files are blinded: no stored mechanism/verdict
is included, only the snippet, the API and the repository, so annotator
agreement estimates the label ceiling of the classification task.
"""

from __future__ import annotations

import argparse
import json
import random
from collections import Counter
from pathlib import Path

HERE = Path(__file__).resolve().parent
OUT = HERE / "out"
DEST = HERE / "adjudication/agreement"


def clip(text: str, head: int = 1400, tail: int = 600) -> str:
    lines = (text or "").strip("\n").splitlines()
    if len(lines) <= 60 and len(text) <= head + tail:
        return text
    return "\n".join(lines[:45]) + "\n...\n" + "\n".join(lines[-20:])


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--y", type=int, default=40)
    ap.add_argument("--retain", type=int, default=20)
    ap.add_argument("--seed", type=int, default=23)
    args = ap.parse_args()

    rows = [json.loads(x) for x in (OUT / "mechanism_dataset_v05.jsonl").open() if x.strip()]
    train = [r for r in rows if r["split"] == "train"]
    y_rows = [r for r in train if r["mechanism"] != "retain"]
    n_rows = [r for r in train if r["mechanism"] == "retain"]
    rng = random.Random(args.seed)
    sample = rng.sample(y_rows, min(args.y, len(y_rows))) + \
        rng.sample(n_rows, min(args.retain, len(n_rows)))
    rng.shuffle(sample)

    DEST.mkdir(parents=True, exist_ok=True)
    with (DEST / "sample.jsonl").open("w") as f:
        for r in sample:
            f.write(json.dumps({
                "id": r["id"],
                "repo": r["repo_key"],
                "api_guess": r.get("api_guess"),
                "old_snippet": clip(r["old_snippet"]),
                "new_snippet": clip(r.get("safe_snippet", "")),
            }, ensure_ascii=False) + "\n")
    stats = {"rows": len(sample),
             "stored": dict(Counter("Y" if r["mechanism"] != "retain" else "retain"
                                    for r in sample))}
    (DEST / "sample_stats.json").write_text(json.dumps(stats, indent=2) + "\n")
    print(json.dumps(stats, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
