"""CLI: detect replaceable-unsafe sinks and emit Y/M/N verdicts.

Unsafe regions, the calls inside them and the raw derefs come from
`safeify-lint --inventory` (rust-analyzer's syntax tree), not from masked
source text; `semantic_inventory` adapts that JSON. LSP hover evidence for the
type-based verdict rules is unchanged and optional.

Usage (from research/):
  source ../.venv/bin/activate   # or any python3 with PyYAML
  python detect/detect.py ../vendors/SafeNet/testdata/ptr::deref \
      --json detect/out/report.json
  python detect/detect.py <file.rs> --no-lsp      # no hover evidence
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass, field
from pathlib import Path

try:
    from . import semantic_inventory, spec_db, verdict
    from .ra_client import Analyzer
except ImportError:  # running as a plain script
    import semantic_inventory
    import spec_db
    import verdict
    from ra_client import Analyzer

import re


@dataclass
class Sink:
    api: str
    kind: str  # "call" | "raw_deref"
    callee: str
    call_text: str
    args: list[str] = field(default_factory=list)
    arg_spans: list[tuple[int, int]] = field(default_factory=list)
    span: tuple[int, int] = (0, 0)
    region: object = None  # semantic_inventory.UnsafeRegion (innermost)


def _receiver_text(src: str, name_start: int) -> str:
    """Best-effort receiver expression before a method name (no spaces)."""
    i = name_start - 1
    while i >= 0 and src[i] in " \t\r\n":
        i -= 1
    if i < 0 or src[i] != ".":
        return ""
    i -= 1
    j = i + 1
    while i >= 0 and (src[i].isalnum() or src[i] in "_.)]"):
        i -= 1
    return re.sub(r"\s+", "", src[i + 1 : j])


def collect_files(paths: list[str]) -> list[Path]:
    out: list[Path] = []
    for p in paths:
        path = Path(p)
        if path.is_dir():
            out.extend(sorted(path.rglob("*.rs")))
        elif path.exists():
            out.append(path)
        else:
            print(f"warn: {p} not found", file=sys.stderr)
    return out


def find_sinks(src: str, inv: semantic_inventory.Inventory,
               db: spec_db.SpecDB) -> list[Sink]:
    """Match spec-DB calls inside unsafe regions; assign to innermost region."""
    def region_for(off: int):
        covers = [r for r in inv.regions if r.covers(off)]
        return min(covers, key=lambda r: r.end - r.start) if covers else None

    sinks: list[Sink] = []
    for r in inv.regions:
        region_sinks: list[Sink] = []
        for c in inv.calls_in(r):
            api = db.match_api(c.callee, c.is_method)
            if not api:
                continue
            s, e = c.span
            if c.is_method:
                recv = _receiver_text(src, s + 1)  # span[0] includes the dot
                text = (f"{recv}.{c.callee}({', '.join(c.args)})" if recv
                        else f"{c.callee}({', '.join(c.args)})")
            else:
                text = src[s:e].strip()
            region_sinks.append(Sink(api, "call", c.callee, text,
                                     list(c.args), list(c.arg_spans),
                                     (s, e), region_for(s)))
        if not region_sinks:
            # no API call: fall back to raw-deref evidence -> ptr::deref family
            for d in inv.derefs_in(r):
                region_sinks.append(Sink("ptr::deref", "raw_deref", d.snippet,
                                         d.snippet, [], [],
                                         (d.offset, d.offset + len(d.snippet)),
                                         region_for(d.offset)))
        sinks.extend(region_sinks)
    # dedupe identical (api, span) pairs across overlapping regions
    seen: set[tuple] = set()
    out: list[Sink] = []
    for s in sinks:
        key = (s.api, s.span)
        if key not in seen:
            seen.add(key)
            out.append(s)
    return out


def gather_evidence(an: "Analyzer | None", src: str, sink: Sink) -> dict:
    """LSP hover evidence: return type (on `)`), arg types (on arg starts)."""
    ev = {"recv_type": None, "arg_types": [], "ret_type": None,
          "lsp": False}
    if an is None or sink.kind != "call":
        return ev
    _s, e = sink.span
    ev["ret_type"] = verdict._type_of_hover(an.hover(e - 1))  # on `)`
    ev["arg_types"] = [verdict._type_of_hover(an.hover(a_start))
                       for a_start, _ in sink.arg_spans]
    ev["lsp"] = True
    return ev


def analyze_file(path: Path, db: spec_db.SpecDB,
                 an: "Analyzer | None") -> dict:
    inv = semantic_inventory.for_file(path)
    src = inv.source
    sinks = find_sinks(src, inv, db)
    rows = []
    for sink in sinks:
        reg = sink.region
        ctx = inv.fn_context(sink.span[0])
        ev = gather_evidence(an, src, sink)
        v = verdict.decide(
            db, sink.api,
            call_text=sink.call_text, args=sink.args,
            recv_type=ev["recv_type"], arg_types=ev["arg_types"],
            ret_type=ev["ret_type"], guards=ctx.guards,
            signature=ctx.signature,
        )
        line, col = semantic_inventory.offset_to_line_col(src, sink.span[0])
        rows.append({
            "file": str(path),
            "line": line + 1,
            "col": col + 1,
            "api": sink.api,
            "kind": sink.kind,
            "callee": sink.callee,
            "call_text": sink.call_text,
            "args": sink.args,
            "span": list(sink.span),
            "region": None if reg is None else {
                "kind": reg.kind, "name": reg.name,
                "span": [reg.start, reg.end],
            },
            "fn": {"name": ctx.fn_name, "signature": ctx.signature,
                   "guards": ctx.guards},
            "evidence": ev,
            "verdict": {
                "v": v.v, "confidence": v.confidence, "reason": v.reason,
                "safe_alternative": v.safe_alternative,
                "encapsulate": v.encapsulate,
                "pattern_hint": v.pattern_hint, "kb_gold": v.kb_gold,
                "rules": v.rules,
            },
        })
    return {"file": str(path), "unsafe_regions": len(inv.regions), "sinks": rows}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("paths", nargs="+", help=".rs files or directories")
    ap.add_argument("--json", metavar="PATH",
                    help="write full JSON report to PATH (- for stdout)")
    ap.add_argument("--no-lsp", action="store_true",
                    help="skip rust-analyzer; syntactic verdicts only")
    ap.add_argument("--ra", default="rust-analyzer", help="rust-analyzer bin")
    args = ap.parse_args(argv)

    db = spec_db.load_spec_db()
    files = collect_files(args.paths)
    if not files:
        print("no .rs files found", file=sys.stderr)
        return 1

    reports = []
    an: Analyzer | None = None
    try:
        for f in files:
            if not args.no_lsp:
                an = Analyzer(ra_bin=args.ra)
                try:
                    an.open_file(f)
                except Exception as ex:  # LSP must never kill the run
                    print(f"warn: LSP failed on {f}: {ex}", file=sys.stderr)
                    an.close()
                    an = None
            try:
                reports.append(analyze_file(f, db, an))
            finally:
                if an is not None:
                    an.close()
                    an = None
    finally:
        if an is not None:
            an.close()

    # human table
    counts = {"Y": 0, "M": 0, "N": 0}
    for rep in reports:
        if not rep["sinks"]:
            print(f"{rep['file']}: 0 sinks ({rep['unsafe_regions']} unsafe "
                  f"region(s))")
            continue
        print(f"{rep['file']}: {len(rep['sinks'])} sink(s), "
              f"{rep['unsafe_regions']} unsafe region(s)")
        for r in rep["sinks"]:
            v = r["verdict"]
            counts[v["v"]] = counts.get(v["v"], 0) + 1
            gold = f" gold={v['kb_gold']}" if v["kb_gold"] else ""
            print(f"  L{r['line']:<4d} {r['api']:22s} {r['call_text'][:40]:42s}"
                  f" -> {v['v']} ({v['confidence']}){gold}")
    print(f"\nverdicts: Y={counts['Y']} M={counts['M']} N={counts['N']} "
          f"files={len(reports)} mode={'no-lsp' if args.no_lsp else 'lsp'}")

    if args.json:
        payload = {"reports": reports,
                   "summary": {"files": len(reports), "verdicts": counts}}
        text = json.dumps(payload, indent=2)
        if args.json == "-":
            print(text)
        else:
            Path(args.json).write_text(text)
            print(f"wrote {args.json}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

