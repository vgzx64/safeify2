#!/usr/bin/env python3
"""Run the semantic engine over the vendored corpus and compare with the text
engine's census.

Usage (from the repository root):
    python3 safeify-lint/corpus/run_semantic_corpus.py [--limit N] [--out FILE]

Emits one JSON array of findings and prints per-rule counts against the recorded
baseline. Finding paths are relative to `safeify-data/` (the engine is run with
that directory as its working directory), which is the convention of the frozen
census and the audit labels.
"""

from __future__ import annotations

import argparse
import concurrent.futures
import json
import subprocess
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
REPO = ROOT
ENGINE = REPO / ".tools" / "cargo-target" / "engine" / "release" / "safeify-lint"
CORPUS = REPO / "safeify-data" / "transitions" / "external" / "crates"
BASELINE = REPO / "safeify-lint" / "out" / "lint_corpus_2026-11-19.json"


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
    ap.add_argument("--out", default=str(REPO / "safeify-lint" / "out" / "lint_corpus_semantic.json"))
    ap.add_argument("--timeout", type=int, default=300, help="seconds per crate")
    ap.add_argument("--jobs", type=int, default=10, help="parallel engine processes")
    ap.add_argument("--restart", action="store_true", help="ignore partial results")
    ap.add_argument("--engine-args", default="", help="extra arguments for safeify-lint")
    ap.add_argument("--stats-out", default=None,
                    help="collect the engine's classification counters here (JSONL)")
    args = ap.parse_args(argv[1:])
    timeout = args.timeout

    findings: list[dict] = []
    failed: list[str] = []
    crates = crate_dirs(args.limit)

    # Incremental output: one JSON line per finished crate, so a long run can be
    # resumed instead of restarted (the engine rebuilds the std sysroot per
    # process, which dominates wall time).
    partial = Path(str(args.out) + ".partial.jsonl")
    done: set[str] = set()
    if partial.is_file() and not args.restart:
        for line in partial.read_text().splitlines():
            try:
                record = json.loads(line)
            except json.JSONDecodeError:
                continue
            done.add(record["crate"])
            findings.extend(record["findings"])
        print(f"resuming: {len(done)} crates already done", file=sys.stderr, flush=True)
    crates = [crate for crate in crates if str(crate) not in done]
    stats_rows: list[dict] = []

    def analyze(crate: Path):
        stats = ["--stats", "-"] if args.stats_out else []
        try:
            proc = subprocess.run(
                [str(ENGINE), "--crate", str(crate), *stats,
                 *(["--extra-cfg"] if args.engine_args else []),
                 *([args.engine_args] if args.engine_args else [])],
                # Paths in the findings are displayed relative to cwd; using the
                # corpus root keeps them in the frozen census convention
                # (`transitions/...`), so census diffs and audit labels match.
                capture_output=True, text=True, cwd=CORPUS.parents[2], timeout=timeout,
            )
        except subprocess.TimeoutExpired:
            return crate, None, None, f"timeout after {timeout}s"
        if proc.returncode != 0:
            return crate, None, None, proc.stderr.strip()[-200:]
        counters = None
        for line in proc.stderr.splitlines():
            if line.startswith("STATS "):
                counters = json.loads(line[len("STATS "):])
        try:
            return crate, json.loads(proc.stdout or "[]"), counters, None
        except json.JSONDecodeError:
            return crate, None, None, "bad json"

    with concurrent.futures.ThreadPoolExecutor(max_workers=args.jobs) as pool:
        futures = {pool.submit(analyze, crate): crate for crate in crates}
        for done, future in enumerate(concurrent.futures.as_completed(futures), 1):
            crate, rows, counters, error = future.result()
            if error is not None:
                failed.append(f"{crate}: {error}")
                print(f"  FAIL {crate}: {error}", file=sys.stderr, flush=True)
            else:
                findings.extend(rows)
                with partial.open("a") as handle:
                    handle.write(json.dumps({"crate": str(crate), "findings": rows}) + "\n")
                if counters is not None:
                    stats_rows.append({"crate": str(crate), **counters})
            if done % 20 == 0:
                print(f"  {done}/{len(crates)} crates, {len(findings)} findings",
                      file=sys.stderr, flush=True)

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
    if partial.is_file():
        partial.unlink()

    print(f"\n{len(unique)} findings across {len({r['path'] for r in unique})} files")
    if args.stats_out and stats_rows:
        Path(args.stats_out).write_text(
            "\n".join(json.dumps(row) for row in stats_rows) + "\n")
        totals: Counter = Counter()
        for row in stats_rows:
            for family in ("fs_calls", "exec_program_calls", "exec_arg_calls"):
                for kind, count in row[family].items():
                    totals[f"{family}.{kind}"] += count
            for knob in ("local_calls", "recursion_cuts", "depth_cuts"):
                totals[knob] += row[knob]
        print("\nclassification counters (all crates):")
        for key in sorted(totals):
            print(f"  {key:28s} {totals[key]:6d}")
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
