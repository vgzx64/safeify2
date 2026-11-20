"""Score a blind spot-check against the current dataset labels.

Usage: python3 score_spotcheck.py <blind.jsonl> <labels.jsonl> <out.json>
"""

from __future__ import annotations

import json
import sys
from collections import Counter, defaultdict
from pathlib import Path

HERE = Path(__file__).resolve().parent
OUT = HERE / "out"


def kappa(pairs: list[tuple[str, str]], labels=("Y", "M", "N", "U")) -> float:
    n = len(pairs)
    if not n:
        return 0.0
    po = sum(1 for a, b in pairs if a == b) / n
    ca = Counter(a for a, _ in pairs)
    cb = Counter(b for _, b in pairs)
    pe = sum((ca[l] / n) * (cb[l] / n) for l in labels)
    return round((po - pe) / (1 - pe), 3) if pe < 1 else 1.0


def main() -> int:
    blind_path, labels_path, dest = sys.argv[1], sys.argv[2], sys.argv[3]
    core = {json.loads(x)["id"]: json.loads(x) for x in (OUT / "transitions_core_v0.2_draft.jsonl").open() if x.strip()}
    blind = [json.loads(x) for x in open(blind_path) if x.strip()]
    new = {json.loads(x)["id"]: json.loads(x) for x in open(labels_path) if x.strip()}

    pairs, rows, disagreements, missing = [], [], [], []
    for b in blind:
        i = b["id"]
        if i not in new:
            missing.append(i)
            continue
        if i not in core:
            missing.append(i)
            continue
        orig = core[i].get("label")
        got = new[i].get("replaceability")
        pairs.append((orig, got))
        rows.append({"id": i, "source": b.get("source"), "original": orig, "second": got,
                     "action": new[i].get("action"), "confidence": new[i].get("confidence"),
                     "rationale": new[i].get("rationale")})
        if orig != got:
            disagreements.append(rows[-1])

    conf = defaultdict(Counter)
    for a, b in pairs:
        conf[a][b] += 1
    per_class = {}
    for l in ("Y", "M", "N"):
        tot = sum(1 for a, _ in pairs if a == l)
        ok = sum(1 for a, b in pairs if a == l and b == l)
        per_class[l] = {"agree": ok, "rows": tot, "rate": round(ok / tot, 3) if tot else None}
    report = {
        "sample": str(Path(blind_path).name),
        "rows": len(pairs),
        "missing_new_labels": missing,
        "raw_agreement": round(sum(1 for a, b in pairs if a == b) / len(pairs), 3) if pairs else None,
        "kappa_3class": kappa(pairs),
        "kappa_y_m_n_only": kappa([(a, b) for a, b in pairs if a in ("Y", "M", "N") and b in ("Y", "M", "N")]),
        "binary_agreement": round(sum(1 for a, b in pairs if (a == "Y") == (b == "Y")) / len(pairs), 3) if pairs else None,
        "binary_kappa": kappa([("Y" if a == "Y" else "not_Y", "Y" if b == "Y" else "not_Y") for a, b in pairs], ("Y", "not_Y")),
        "per_class_agreement": per_class,
        "confusion_original_rows_new_cols": {a: dict(c) for a, c in conf.items()},
        "disagreements": disagreements,
    }
    Path(dest).write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
