#!/usr/bin/env python3
"""Union the cfg-specific engine passes and diff the result against a census.

The semantic engine is run once per cfg configuration (host, and a Windows pass
with `--extra-cfg windows,target_family=windows,target_os=windows`), because
`cfg` selects different code. Findings are de-duplicated by
`(rule, path, line)` so a site reported by both passes counts once.

The census is the frozen text-engine artifact (`lint_corpus_2026-11-19.json`).
This script is the only supported way to state corpus-level numbers, so every
number in `notes/research/engine.md` can be regenerated from committed files.

Usage (from `research/`):
    python3 detect/corpus_report.py \
        --union detect/out/a.json detect/out/b.json \
        --baseline detect/out/lint_corpus_2026-11-19.json \
        --out detect/out/union.json
"""

from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path


def key(f: dict) -> tuple[str, str, int]:
    return (f["rule"], str(Path(f["path"])), int(f["line"]))


def load(path: Path) -> list[dict]:
    rows = json.loads(path.read_text())
    if not isinstance(rows, list):
        raise SystemExit(f"{path}: expected a JSON list of findings")
    return rows


def union(paths: list[Path]) -> list[dict]:
    seen: dict[tuple[str, str, int], dict] = {}
    for path in paths:
        for row in load(path):
            k = key(row)
            if k in seen:
                if seen[k]["level"] != row["level"]:
                    raise SystemExit(
                        f"{k}: passes disagree on level "
                        f"({seen[k]['level']} vs {row['level']})"
                    )
                continue
            seen[k] = row
    return [seen[k] for k in sorted(seen)]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--union", nargs="+", required=True, type=Path,
                    help="pass artifacts to union")
    ap.add_argument("--baseline", type=Path, help="census to diff against")
    ap.add_argument("--out", type=Path, help="write the union here")
    ap.add_argument("--list-limit", type=int, default=12,
                    help="sites to list per bucket (0: all)")
    args = ap.parse_args()

    merged = union(args.union)
    per_rule = Counter(f["rule"] for f in merged)
    per_level = Counter(f["level"] for f in merged)
    files = {str(Path(f["path"])) for f in merged}
    print(f"union: {len(merged)} findings in {len(files)} files "
          f"from {len(args.union)} passes")
    print("  by rule:  " + ", ".join(f"{r} {n}" for r, n in sorted(per_rule.items())))
    print("  by level: " + ", ".join(f"{l} {n}" for l, n in sorted(per_level.items())))

    if args.out:
        args.out.write_text(json.dumps(merged, indent=2) + "\n")
        print(f"wrote {args.out}")

    if args.baseline:
        base = load(args.baseline)
        old = {key(f) for f in base}
        new = {key(f) for f in merged}
        common = old & new
        print(f"\nbaseline: {len(old)} findings in "
              f"{len({str(Path(f['path'])) for f in base})} files")
        print(f"  common {len(common)}  old-only {len(old - new)}  "
              f"new-only {len(new - old)}")
        print("\nby rule (baseline / union / common / old-only / new-only):")
        rules = sorted({r for r, _, _ in old | new})
        for rule in rules:
            o = {k for k in old if k[0] == rule}
            n = {k for k in new if k[0] == rule}
            print(f"  {rule:26s} {len(o):4d} {len(n):4d} {len(o & n):4d} "
                  f"{len(o - n):4d} {len(n - o):4d}")
        limit = args.list_limit or None
        for label, sites in (("old-only", old - new), ("new-only", new - old)):
            if not sites:
                continue
            print(f"\n{label} ({len(sites)}):")
            for rule, path, line in sorted(sites)[:limit]:
                print(f"  {rule:26s} {path}:{line}")
            if limit and len(sites) > limit:
                print(f"  ... {len(sites) - limit} more")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
