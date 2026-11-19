"""Ablation: side-effect enumeration vs the lint's filtered output.

The honest novelty claim for the safe-Rust lints is not "we find OS side
effects" — Cargo Scan already enumerates those, and the paper used it for its
prevalence numbers. The claim is that the provenance + guard layer removes the
overwhelming majority of side effects that are not actionable, and leaves a
short list a reviewer can read.

This script counts both sides on the same corpus:

  candidates  every call to a sink family (what an enumerator reports)
  findings    what lint_safe actually reports
  buckets     why the rest was dropped: literal-safe, guarded, read, unknown

Run from research/:
  python detect/ablate_lints.py transitions/external/crates --max-bytes 100000
"""

from __future__ import annotations

import argparse
import collections
import json
import sys
from pathlib import Path

try:
    from . import inventory, lint_safe
    from .provenance import classify, fn_at, guards_for, parse_fns, stmt_start
except ImportError:
    import inventory
    import lint_safe
    from provenance import classify, fn_at, guards_for, parse_fns, stmt_start


def family_of(call) -> str | None:
    if call.is_method:
        return "fs" if call.callee in {"open", "create", "create_new"} else None
    tail = lint_safe._tail2(call.callee)
    if tail in lint_safe.FS_PATH_ARG:
        return "fs"
    if tail == "Command::new":
        return "exec"
    if tail in {"env::set_var", "env::remove_var", "env::var", "env::var_os"}:
        return "env"
    return None


def run(paths: list[str], max_bytes: int) -> dict:
    files = []
    for raw in paths:
        p = Path(raw)
        if p.is_dir():
            files += sorted(
                q for q in p.rglob("*.rs")
                if "target" not in q.parts and ".git" not in q.parts
            )
        elif p.is_file():
            files.append(p)

    families = collections.Counter()
    buckets = collections.Counter()
    rule_hits = collections.Counter()
    n_files = 0

    for f in files:
        try:
            if max_bytes and f.stat().st_size > max_bytes:
                continue
            src = f.read_text(errors="replace")
        except OSError:
            continue
        n_files += 1
        mask = inventory.mask_source(src)
        fns = parse_fns(src, mask)
        for call in lint_safe.interesting_calls(mask):
            fam = family_of(call)
            if fam is None:
                continue
            families[fam] += 1
            shim = type("C", (), {"mask": mask})()
            fn = fn_at(fns, call.open_paren)
            if fn is None:
                buckets[f"{fam}:no_fn"] += 1
                continue
            if fam == "fs":
                if call.is_method:
                    idxs = (0,)
                else:
                    idxs = lint_safe.FS_PATH_ARG.get(lint_safe._tail2(call.callee), ())
                if not idxs:
                    buckets["fs:not_a_path_arg"] += 1
                    continue
                i = idxs[0]
                if i >= len(call.arg_spans):
                    buckets["fs:no_arg"] += 1
                    continue
                a, b = call.arg_spans[i]
                expr = src[a:b].strip()
                prov = classify(expr, fn)
                if prov.is_literal():
                    level = "danger" if lint_safe.danger_path(prov.value or "") else "safe"
                    buckets[f"fs:literal_{level}"] += 1
                elif prov.is_trusted():
                    buckets["fs:trusted_env"] += 1
                elif prov.is_dynamic():
                    if not lint_safe._is_write_sink(shim, call):
                        buckets["fs:read_dynamic"] += 1
                    elif guards_for(mask, expr, fn.body_start, call.open_paren):
                        buckets["fs:guarded"] += 1
                    else:
                        buckets["fs:reported"] += 1
                else:
                    buckets["fs:unknown"] += 1
            elif fam == "exec":
                prov = classify(src[call.arg_spans[0][0] : call.arg_spans[0][1]].strip(), fn) if call.arg_spans else None
                if prov is None:
                    buckets["exec:no_arg"] += 1
                elif prov.is_literal():
                    buckets["exec:literal_basename" if "/" not in (prov.value or "") else "exec:literal_path"] += 1
                elif prov.is_dynamic():
                    buckets["exec:dynamic"] += 1
                else:
                    buckets["exec:unknown"] += 1
            else:
                buckets["env:call"] += 1

        for finding in lint_safe.lint_source(src, path=str(f)):
            rule_hits[finding.rule] += 1

    return {
        "files": n_files,
        "families": dict(families),
        "buckets": dict(buckets),
        "rules": dict(rule_hits),
    }


def report(stats: dict) -> None:
    fam = stats["families"]
    total = sum(fam.values())
    print(f"files: {stats['files']}")
    print("candidate side-effect calls:", dict(fam), f"(total {total})")
    print("\nbuckets:")
    for key, n in sorted(stats["buckets"].items(), key=lambda kv: -kv[1]):
        print(f"  {n:6d}  {key}")
    print("\nfindings by rule:", dict(stats["rules"]))
    n_findings = sum(stats["rules"].values())
    if total:
        print(
            f"\n{total} enumerated call sites -> {n_findings} findings "
            f"({100 * n_findings / total:.1f}% survive)"
        )


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("paths", nargs="+")
    ap.add_argument("--max-bytes", type=int, default=0)
    ap.add_argument("--json", help="write the raw counts here")
    args = ap.parse_args(argv)
    stats = run(args.paths, args.max_bytes)
    report(stats)
    if args.json:
        Path(args.json).write_text(json.dumps(stats, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
