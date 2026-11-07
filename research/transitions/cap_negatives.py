"""Cap the unsafe-to-unsafe pool and drop signature-only rows.

Writes out/negative_pool_capped.csv: at most three non-signature rows per
repository. The 28-row audit sample is selected separately with seed 42.
"""

from __future__ import annotations

import csv
from collections import defaultdict
from pathlib import Path

OUT = Path(__file__).resolve().parent / "out"


def main() -> int:
    rows = list(csv.DictReader((OUT / "unsafe_audit.csv").open()))
    non_sig = [r for r in rows if r.get("auto_category") != "signature"]
    by_repo = defaultdict(list)
    for r in non_sig:
        by_repo[r["repo"]].append(r)
    capped = []
    for repo, rs in sorted(by_repo.items()):
        capped.extend(sorted(rs, key=lambda r: (r["path"], r["span_start"]))[:3])
    with (OUT / "negative_pool_capped.csv").open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(capped)
    print(f"all={len(rows)} non_signature={len(non_sig)} capped={len(capped)} repos={len(by_repo)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
