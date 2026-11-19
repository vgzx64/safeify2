#!/usr/bin/env python3
"""Differential harness: text engine (`lint_safe.py`) vs semantic engine
(`safeify-lint`).

Both engines report `(rule, file, line)`. This script normalizes and diffs
them per crate, which is the gate for retiring the text implementation of a
rule: a rule is ported when every difference is explained (capability gain,
text-engine false positive, or a site the semantic engine cannot see).

Usage:
    python3 detect/compare_engines.py CRATE_DIR [CRATE_DIR ...]

Run from `research/` so relative paths line up with the old engine's output.
"""

from __future__ import annotations

import json
import subprocess
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ENGINE = ROOT.parent / ".tools" / "cargo-target" / "engine" / "release" / "safeify-lint"


def sitename(path: str, line: int, rule: str) -> tuple[str, str, int]:
    return (rule, str(Path(path)), int(line))


def old_findings(crate: Path) -> set[tuple[str, str, int]]:
    out = subprocess.run(
        [sys.executable, "detect/lint_safe.py", "--json", "--no-config",
         "--edition", "2021", "--max-bytes", "100000", str(crate)],
        capture_output=True, text=True, cwd=ROOT,
    )
    if out.returncode != 0:
        raise SystemExit(f"old engine failed on {crate}: {out.stderr[-400:]}")
    rows = json.loads(out.stdout or "[]")
    return {sitename(r["path"], r["line"], r["rule"]) for r in rows}


def new_findings(crate: Path) -> set[tuple[str, str, int]]:
    out = subprocess.run(
        [str(ENGINE), "--crate", str(crate)],
        capture_output=True, text=True, cwd=ROOT,
    )
    if out.returncode != 0:
        raise SystemExit(f"semantic engine failed on {crate}: {out.stderr[-400:]}")
    rows = json.loads(out.stdout or "[]")
    return {sitename(r["path"], r["line"], r["rule"]) for r in rows}


def main(argv: list[str]) -> int:
    crates = [Path(a) for a in argv[1:]]
    if not crates:
        print(__doc__)
        return 2
    totals: dict[str, list[int]] = defaultdict(lambda: [0, 0, 0, 0])  # old, new, common, diff
    for crate in crates:
        old, new = old_findings(crate), new_findings(crate)
        print(f"\n== {crate}")
        rules = sorted({r for r, _, _ in old | new})
        for rule in rules:
            o = {s for s in old if s[0] == rule}
            n = {s for s in new if s[0] == rule}
            common = o & n
            bucket = totals[rule]
            bucket[0] += len(o)
            bucket[1] += len(n)
            bucket[2] += len(common)
            bucket[3] += len(o ^ n)
            print(f"  {rule:24s} old {len(o):3d}  new {len(n):3d}  common {len(common):3d}"
                  f"  old-only {len(o - n):3d}  new-only {len(n - o):3d}")
        for label, extra in (("old-only", old - new), ("new-only", new - old)):
            for rule, path, line in sorted(extra)[:6]:
                print(f"    {label}: {rule} {path}:{line}")
    print("\n== totals by rule (old/new/common/symmetric-diff)")
    for rule, (o, n, c, d) in sorted(totals.items()):
        print(f"  {rule:24s} {o:4d} {n:4d} {c:4d} {d:4d}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
