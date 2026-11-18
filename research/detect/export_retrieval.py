"""Export detector pattern hints as `--retrieval-preds` for eval_protocol.py.

DoD #3 asks for `eval_protocol.py --retrieval-preds` on the frozen 97-file
test split. NIRM 3 does not implement a retrieval model; the detector emits a
KB `pattern_hint` for the sinks whose shape it can classify. This script turns
those hints into the expected `[{id, pattern_id}, ...]` file so the DoD item can
be scored honestly.

Rule per file (deterministic):
  - take the most frequent non-null `pattern_hint` over the file's sinks;
  - ties -> smallest pattern id;
  - files with no hint get pattern_id 0 ("no claim"), which the scorer counts
    as a miss.

So the resulting accuracy is a LOWER BOUND for "the detector as a retriever",
not the performance of a nearest-neighbour retrieval model (that is NIRM 4).

Usage (from research/):
  python detect/export_retrieval.py detect/out/nirm3_eval_lsp.json \
      --out detect/out/nirm3_retrieval_lsp.json
  python synth/splits/eval_protocol.py --retrieval-preds \
      detect/out/nirm3_retrieval_lsp.json
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from score_frozen import load_gold, rel_testdata  # noqa: E402


def modal_hint(sinks: list[dict]) -> int:
    counts = Counter(s["verdict"]["pattern_hint"] for s in sinks
                     if s["verdict"].get("pattern_hint"))
    if not counts:
        return 0  # no claim; scorer counts it as a miss
    return sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))[0][0]


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("report", help="detect.py JSON report")
    ap.add_argument("--out", required=True, help="retrieval-preds JSON path")
    args = ap.parse_args(argv)

    report = json.loads(Path(args.report).read_text())
    by_rel: dict[str, list[dict]] = {}
    for rep in report["reports"]:
        rel = rel_testdata(rep["file"])
        if rel:
            by_rel[rel] = rep["sinks"]

    gold = load_gold()
    missing = sorted(set(gold) - set(by_rel))
    if missing:
        sys.exit(f"report does not cover {len(missing)} test file(s): "
                 f"{missing[:3]}")

    preds = [{"id": rel, "pattern_id": modal_hint(by_rel[rel])}
             for rel in sorted(gold)]
    claimed = sum(1 for p in preds if p["pattern_id"])
    Path(args.out).write_text(json.dumps(preds, indent=1) + "\n")
    print(f"wrote {args.out}: {len(preds)} queries, "
          f"{claimed} with a pattern claim "
          f"({claimed / len(preds):.3f} coverage)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
