"""Score the rule labeller against the 139 audited mechanisms.

Reports overall agreement, per-mechanism recall, and where the rules fire at
all (coverage). A rule that returns None is counted as "no prediction", not as
a wrong class, so precision of the firing rules is visible.
"""

from __future__ import annotations

import json
from collections import Counter, defaultdict
from pathlib import Path

from mechanism_rules import predict

OUT = Path(__file__).resolve().parent / "out"


def main() -> int:
    rows = [json.loads(x) for x in (OUT / "mechanism_dataset.jsonl").open() if x.strip()]
    y_rows = [r for r in rows if r["mechanism"] != "retain"]
    pairs = Counter()
    per_class = defaultdict(lambda: {"n": 0, "fired": 0, "correct": 0})
    for r in y_rows:
        pred = predict(r["old_snippet"], r.get("safe_snippet", ""), r.get("api_guess"))
        key = (r["mechanism"], pred or "no_prediction")
        pairs[key] += 1
        c = per_class[r["mechanism"]]
        c["n"] += 1
        c["fired"] += pred is not None
        c["correct"] += pred == r["mechanism"]
    fired = sum(1 for r in y_rows
                if predict(r["old_snippet"], r.get("safe_snippet", ""), r.get("api_guess")))
    correct = sum(1 for r in y_rows
                  if predict(r["old_snippet"], r.get("safe_snippet", ""), r.get("api_guess"))
                  == r["mechanism"])
    report = {
        "rows": len(y_rows),
        "coverage": fired / len(y_rows),
        "precision_when_fired": correct / fired if fired else None,
        "accuracy_all_rows": correct / len(y_rows),
        "per_class": {k: dict(v) for k, v in sorted(per_class.items())},
        "confusion": [{"true": a, "pred": b, "n": n} for (a, b), n in pairs.most_common()],
    }
    (OUT / "mechanism_rules_score.json").write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps({k: report[k] for k in
                      ("rows", "coverage", "precision_when_fired", "accuracy_all_rows")},
                     indent=2))
    print("per-class:", {k: f"{v['correct']}/{v['n']}" for k, v in report["per_class"].items()})
    print("top confusion:", report["confusion"][:8])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
