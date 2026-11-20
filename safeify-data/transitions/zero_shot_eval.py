"""Zero-shot evaluation of the current detector on transition snippets.

Positive rows: a safe replacement exists in the fix (expected Y).
Hard negatives: unsafe remains and is not replaced (expected N/M).
Guard rows: unsafe remains but is guarded/conditional (expected M).

The detector is syntactic (--no-lsp) and is not retrained.
"""

from __future__ import annotations

import csv
import json
import re
import subprocess
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
OUT = Path(__file__).resolve().parent / "out"
WORK = OUT / "zero_shot"
DETECT = ROOT / "research" / "detect" / "detect.py"


def norm_id(s: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.-]+", "_", s)[:120]


def as_file(snippet: str) -> str:
    """Make a parseable-ish Rust file from a hunk snippet."""
    if re.search(r"\b(?:fn|impl|trait|struct|enum|mod)\b", snippet):
        return snippet + ("\n" if not snippet.endswith("\n") else "")
    return "fn main() {\n" + snippet + "\n}\n"


def main() -> int:
    rows = [json.loads(x) for x in (OUT / "manifest.jsonl").open()]
    positives = [
        r for r in rows
        if r["observed"] == "safe" and r["label"] == "safe_replacement"
    ]
    negatives = list(csv.DictReader((OUT / "negative_sample_audit.csv").open()))
    selected_neg = [r for r in negatives if r["label"] in ("hard_negative", "guard")]

    inputs = WORK / "inputs"
    inputs.mkdir(parents=True, exist_ok=True)
    mapping = {}
    entries = []
    for i, r in enumerate(positives):
        name = f"p{i:03d}.rs"
        (inputs / name).write_text(as_file(r["old_snippet"]))
        mapping[name] = {"group": "positive", "expected": "Y", "id": r["id"],
                         "repo": r["repo_name"], "cve": r["cve_id"]}
        entries.append(mapping[name])
    for i, r in enumerate(selected_neg):
        name = f"n{i:03d}.rs"
        (inputs / name).write_text(as_file(r["old_snippet"]))
        mapping[name] = {"group": "negative", "expected": "N_or_M", "id": r["id"],
                         "negative_label": r["label"], "repo": r["repo"],
                         "cve": r["cve"]}
        entries.append(mapping[name])

    report = OUT / "zero_shot" / "detect_report.json"
    proc = subprocess.run(
        [sys.executable, str(DETECT), str(inputs), "--no-lsp", "--json", str(report)],
        capture_output=True, text=True, cwd=ROOT,
    )
    (OUT / "zero_shot" / "detect_stdout.txt").write_text(proc.stdout + "\n" + proc.stderr)
    if not report.exists():
        print("detector failed; see detect_stdout.txt", file=sys.stderr)
        return 1

    rep = json.loads(report.read_text())
    by_name = {}
    for r in rep.get("reports", []):
        by_name[Path(r["file"]).name] = r

    summary = Counter()
    details = []
    for name, meta in mapping.items():
        rr = by_name.get(name)
        sinks = rr.get("sinks", []) if rr else []
        verdicts = [s["verdict"]["v"] for s in sinks]
        summary[(meta["group"], "files")] += 1
        if not sinks:
            summary[(meta["group"], "no_sink")] += 1
        for v in ("Y", "M", "N"):
            summary[(meta["group"], v)] += verdicts.count(v)
        if meta["group"] == "positive" and "Y" in verdicts:
            summary[("positive", "has_Y")] += 1
        if meta["group"] == "negative" and "Y" in verdicts:
            summary[("negative", "dangerous_Y")] += 1
        details.append({
            **meta, "file": name, "sinks": len(sinks), "verdicts": verdicts,
            "apis": [s.get("api") for s in sinks],
        })

    out = {"summary": {f"{k[0]}:{k[1]}": v for k, v in sorted(summary.items())},
           "details": details}
    (OUT / "zero_shot" / "summary.json").write_text(json.dumps(out, indent=2) + "\n")
    print(json.dumps(out["summary"], indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
