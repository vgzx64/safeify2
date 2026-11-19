#!/usr/bin/env python3
"""Run the semantic engine over the vendored corpus and compare with the text
engine's census.

Usage (from `research/`):
    python3 detect/run_semantic_corpus.py [--limit N] [--out FILE]

Emits one JSON array of findings (same schema as `lint_safe.py --json`) and
prints per-rule counts against the recorded baseline.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent          # research/
REPO = ROOT.parent
ENGINE = REPO / ".tools" / "cargo-target" / "engine" / "release" / "safeify-lint"
CORPUS = ROOT / "transitions" / "external" / "crates"
BASELINE = ROOT / "detect" / "out" / "lint_corpus_2026-11-19.json"


def crate_dirs(limit: int | None) -> list[Path]:
    dirs = sorted(
        d for d in CORPUS.glob("*/*/*") if (d / "Cargo.toml").is_file()
    )
    if limit:
        dirs = dirs[:limit]
    return dirs


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=None)
    ap.add_argument("--out", default=str(ROOT / "detect" / "out" / "lint_corpus_semantic_2026-11-19.json"))
    ap.add_argument("--timeout", type=int, default=180, help="seconds per crate")
    args = ap.parse_args(argv[1:])
    timeout = args.timeout

    findings: list[dict] = []
    failed: list[str] = []
    for index, crate in enumerate(crate_dirs(args.limit), 1):
        try:
            proc = subprocess.run(
                [str(ENGINE), "--crate", str(crate)],
                capture_output=True, text=True, cwd=ROOT, timeout=timeout,
            )
        except subprocess.TimeoutExpired:
            failed.append(f"{crate}: timeout after {timeout}s")
            print(f"  TIMEOUT {crate}", file=sys.stderr, flush=True)
            continue
        if proc.returncode != 0:
            failed.append(f"{crate}: {proc.stderr.strip()[-200:]}")
            print(f"  FAIL {crate}: {proc.stderr.strip()[-160:]}", file=sys.stderr, flush=True)
            continue
        try:
            findings.extend(json.loads(proc.stdout or "[]"))
        except json.JSONDecodeError:
            failed.append(f"{crate}: bad json")
        if index % 10 == 0:
            print(f"  {index} crates, {len(findings)} findings", file=sys.stderr, flush=True)

    seen = set()
    unique = []
    for row in findings:
        key = (row["rule"], row["path"], row["line"])
        if key in seen:
            continue
        seen.add(key)
        unique.append(row)
    unique.sort(key=lambda r: (r["path"], r["line"], r["rule"]))
    Path(args.out).write_text(json.dumps(unique, indent=1) + "\n")

    print(f"\n{len(unique)} findings across {len({r['path'] for r in unique})} files")
    if failed:
        print(f"{len(failed)} crates failed:")
        for line in failed[:10]:
            print("  " + line)

    old = json.loads(BASELINE.read_text()) if BASELINE.is_file() else []
    old_rules = Counter(r["rule"] for r in old)
    new_rules = Counter(r["rule"] for r in unique)
    print(f"\n{'rule':24s} {'old':>5s} {'new':>5s} {'common':>7s} {'old-only':>9s} {'new-only':>9s}")
    old_sites = {(r["rule"], r["path"], r["line"]) for r in old}
    new_sites = {(r["rule"], r["path"], r["line"]) for r in unique}
    for rule in sorted(set(old_rules) | set(new_rules)):
        o = {s for s in old_sites if s[0] == rule}
        n = {s for s in new_sites if s[0] == rule}
        print(f"{rule:24s} {len(o):5d} {len(n):5d} {len(o & n):7d} {len(o - n):9d} {len(n - o):9d}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
