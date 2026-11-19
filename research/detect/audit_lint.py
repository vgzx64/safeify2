"""Deterministic precision audit for the safe-Rust lints.

Reads a `lint_safe.py --json` corpus report, deduplicates findings that are the
same code site repeated across crate versions, builds an audit sheet with the
source window of each site, and (with `--stats`) computes precision with
Wilson 95% intervals from the labels recorded in the sheet.

Labels:
  TP   correct detection, actionable
  TL   correct detection, but ubiquitous/low-value (still not an error)
  FP   wrong: the code is not an instance of the pattern
  FX   out of scope / cannot judge from source

Run from research/:
  python detect/audit_lint.py --corpus detect/out/lint_corpus_2026-11-19.json \
      --sheet detect/out/lint_audit_2026-11-19.jsonl --info-sample 40
  python detect/audit_lint.py --sheet detect/out/lint_audit_2026-11-19.jsonl --stats
"""

from __future__ import annotations

import argparse
import json
import math
import random
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
AUDITABLE = ("deny", "warn")


def strip_versions(path: str) -> tuple[str, str]:
    """(crate, path suffix after the version directory) for deduplication."""
    parts = path.split("/")
    if "crates" not in parts:
        return "", path
    i = parts.index("crates")
    crate = parts[i + 1] if i + 1 < len(parts) else ""
    rest = parts[i + 2 :]
    while rest and re.match(r"^\d", rest[0]):
        rest = rest[1:]
    if rest and rest[0].startswith(crate + "-"):
        rest = rest[1:]
    return crate, "/".join(rest)


def norm(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def window(src: str, line: int, before: int = 4, after: int = 4) -> str:
    lines = src.splitlines()
    i = max(0, line - 1 - before)
    j = min(len(lines), line + after)
    out = []
    for n in range(i, j):
        mark = ">" if n == line - 1 else " "
        out.append(f"{mark}{n + 1:5d} {lines[n]}")
    return "\n".join(out)


def build(corpus: Path, sheet: Path, info_sample: int, seed: int) -> None:
    data = json.loads(corpus.read_text())
    seen: set[tuple] = set()
    sites: list[dict] = []
    for f in data:
        rel = Path(f["path"])
        abs_path = ROOT / "research" / rel
        try:
            src = abs_path.read_text(errors="replace")
        except OSError:
            continue
        win = window(src, f["line"])
        crate, rest = strip_versions(f["path"])
        key = (f["rule"], crate, rest, norm(win.split("\n", 5)[-1]))
        if key in seen:
            continue
        seen.add(key)
        sites.append(
            {
                "id": f"{f['rule']}:{len(sites):03d}",
                "rule": f["rule"],
                "level": f["level"],
                "path": f["path"],
                "line": f["line"],
                "window": win,
                "label": "",
                "note": "",
            }
        )

    actionable = [s for s in sites if s["level"] in AUDITABLE]
    info = [s for s in sites if s["level"] not in AUDITABLE]
    rng = random.Random(seed)
    picked_info = rng.sample(info, min(info_sample, len(info)))

    sheet.parent.mkdir(parents=True, exist_ok=True)
    with sheet.open("w") as fh:
        for s in actionable + picked_info:
            fh.write(json.dumps(s, ensure_ascii=False) + "\n")
    print(f"{len(sites)} unique sites; {len(actionable)} actionable, "
          f"{len(info)} info; sheet rows: {len(actionable) + len(picked_info)}")


def wilson(k: int, n: int, z: float = 1.96) -> tuple[float, float]:
    if n == 0:
        return (0.0, 0.0)
    p = k / n
    d = 1 + z * z / n
    c = p + z * z / (2 * n)
    h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n))
    return ((c - h) / d, (c + h) / d)


def cluster_bootstrap(rows: list[dict], z: float = 1.96, reps: int = 2000,
                      seed: int = 1234) -> tuple[float, float]:
    """Percentile interval resampling crates, not findings.

    Findings cluster hard: one build script can contribute a dozen sites and
    one crate can dominate the census. Resampling findings would understate
    the interval.
    """
    rng = random.Random(seed)
    by_crate: dict[str, list[bool]] = {}
    for r in rows:
        crate, _ = strip_versions(r["path"])
        by_crate.setdefault(crate, []).append(r["label"] in ("TP", "TL"))
    crates = list(by_crate)
    if len(crates) < 2:
        return (0.0, 1.0)
    estimates = []
    for _ in range(reps):
        pick = [by_crate[crates[rng.randrange(len(crates))]] for _ in crates]
        total = sum(len(v) for v in pick)
        good = sum(sum(v) for v in pick)
        estimates.append(good / total if total else 0.0)
    estimates.sort()
    lo = estimates[int(0.025 * len(estimates))]
    hi = estimates[int(0.975 * len(estimates))]
    return (lo, hi)


def stats(sheet: Path, labels_path: Path | None) -> None:
    rows = [json.loads(l) for l in sheet.read_text().splitlines() if l.strip()]
    if labels_path is not None:
        labels = json.loads(labels_path.read_text())
        for r in rows:
            key = f"{r['rule']}|{r['path']}|{r['line']}"
            if key in labels:
                r["label"] = labels[key]["label"]
                r["note"] = labels[key].get("note", "")
    labeled = [r for r in rows if r["label"]]
    print(f"rows: {len(rows)}, labeled: {len(labeled)}")
    bad = [r for r in labeled if r["label"] not in ("TP", "TL", "FP", "FX")]
    if bad:
        print(f"invalid labels: {[(r['id'], r['label']) for r in bad]}")
        return

    def report(name: str, subset: list[dict]) -> None:
        n = len(subset)
        if not n:
            return
        good = sum(1 for r in subset if r["label"] in ("TP", "TL"))
        strict = sum(1 for r in subset if r["label"] == "TP")
        lo, hi = wilson(good, n)
        lo2, hi2 = wilson(strict, n)
        clo, chi = cluster_bootstrap(subset)
        print(
            f"{name:26s} n={n:3d}  correct={good:3d} ({good / n:.2f} "
            f"[{lo:.2f},{hi:.2f}] cluster [{clo:.2f},{chi:.2f}])  "
            f"strict TP={strict:3d} ({strict / n:.2f} [{lo2:.2f},{hi2:.2f}])"
        )

    report("all", labeled)
    for level in ("deny", "warn", "info"):
        report(f"level={level}", [r for r in labeled if r["level"] == level])
    rules = sorted({r["rule"] for r in labeled})
    for rule in rules:
        report(rule, [r for r in labeled if r["rule"] == rule])


def show(sheet: Path, start: int, count: int) -> None:
    rows = [json.loads(l) for l in sheet.read_text().splitlines() if l.strip()]
    for r in rows[start : start + count]:
        print("=" * 78)
        print(f"{r['id']}  {r['level']:5s} {r['rule']}  {r['path']}:{r['line']}")
        print(r["window"])


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--corpus")
    ap.add_argument("--sheet", required=True)
    ap.add_argument("--info-sample", type=int, default=40)
    ap.add_argument("--seed", type=int, default=1234)
    ap.add_argument("--stats", action="store_true")
    ap.add_argument("--labels", help="JSON labels keyed by rule|path|line")
    ap.add_argument("--show", nargs=2, type=int, metavar=("START", "COUNT"))
    args = ap.parse_args(argv)
    sheet = Path(args.sheet)
    if args.corpus:
        build(Path(args.corpus), sheet, args.info_sample, args.seed)
    if args.stats:
        stats(sheet, Path(args.labels) if args.labels else None)
    if args.show:
        show(sheet, args.show[0], args.show[1])
    return 0


if __name__ == "__main__":
    sys.exit(main())
