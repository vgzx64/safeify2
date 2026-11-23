"""Blind hazard-label batches for a stratified train sample (human-supervised)."""
from __future__ import annotations
import argparse, json, random
from collections import Counter
from pathlib import Path

HERE = Path(__file__).resolve().parent
OUT = HERE / "out"
DEST = HERE / "adjudication/hazard_train"


def clip(text: str, head: int = 1400, tail: int = 600) -> str:
    lines = (text or "").strip("\n").splitlines()
    if len(lines) <= 60 and len(text) <= head + tail:
        return text
    return "\n".join(lines[:45]) + "\n...\n" + "\n".join(lines[-20:])


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--sample", type=int, default=300)
    ap.add_argument("--rows-per-batch", type=int, default=38)
    ap.add_argument("--seed", type=int, default=41)
    args = ap.parse_args()

    rows = [json.loads(x) for x in (OUT / "mechanism_dataset_v05.jsonl").open() if x.strip()]
    rules = {r["id"]: r["hazard"] for r in
             (json.loads(x) for x in (OUT / "hazard_labels.jsonl").open() if x.strip())}
    train = [r for r in rows if r["split"] == "train"]
    rng = random.Random(args.seed)
    grouped = {}
    for r in train:
        grouped.setdefault(rules[r["id"]], []).append(r)
    total = len(train)
    CAP = {"unsafe_call": 40, "unknown": 10}
    picked, leftovers = [], []
    for hazard, rs in grouped.items():
        rng.shuffle(rs)
        quota = max(10, round(args.sample * len(rs) / total))
        quota = min(quota, len(rs), CAP.get(hazard, len(rs)))
        picked.extend(rs[:quota])
        leftovers.extend(rs[quota:])
    # top up with the non-residual classes so small hazards get support
    rng.shuffle(leftovers)
    extra = [r for r in leftovers if rules[r["id"]] not in ("unsafe_call", "unknown")]
    picked.extend(extra[: max(0, args.sample - len(picked))])
    rng.shuffle(picked)
    picked = picked[: args.sample]

    DEST.mkdir(parents=True, exist_ok=True)
    for i in range(0, len(picked), args.rows_per_batch):
        chunk = picked[i:i + args.rows_per_batch]
        name = f"batch_{i // args.rows_per_batch + 1:02d}.jsonl"
        with (DEST / name).open("w") as f:
            for r in chunk:
                f.write(json.dumps({"id": r["id"], "repo": r["repo_key"],
                                    "old_snippet": clip(r["old_snippet"])},
                                   ensure_ascii=False) + "\n")
        print(name, len(chunk))
    print("total", len(picked), "rule dist", dict(Counter(rules[r['id']] for r in picked).most_common()))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
