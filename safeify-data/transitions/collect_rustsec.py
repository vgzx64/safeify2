"""Inventory RustSec advisories and compare them with CVEfixes."""

from __future__ import annotations

import json
import re
import sqlite3
import tomllib
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
ADV = ROOT / "safeify-data" / "transitions" / "external" / "rustsec-advisory-db" / "crates"
DB = ROOT / "rust_ecosystem" / "CVEfixes.db"
OUT = Path(__file__).resolve().parent / "out"


def parse(path: Path):
    text = path.read_text(encoding="utf-8", errors="replace")
    m = re.search(r"```toml\n(.*?)\n```", text, re.S)
    if not m:
        return None
    return tomllib.loads(m.group(1))


def main() -> int:
    con = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
    known = set()
    for r in con.execute("select id from cve"):
        known.add(str(r[0]))
    for r in con.execute("select advisory_id from cve_advisory"):
        if r[0]:
            known.add(str(r[0]))
    con.close()

    rows = []
    for path in sorted(ADV.rglob("*.md")):
        data = parse(path)
        if not data:
            continue
        adv = data.get("advisory", {})
        versions = data.get("versions", {})
        ids = {adv.get("id"), *(adv.get("aliases") or [])}
        rows.append({
            "path": str(path.relative_to(ADV)),
            "id": adv.get("id"),
            "package": adv.get("package"),
            "date": adv.get("date"),
            "url": adv.get("url"),
            "categories": adv.get("categories") or [],
            "aliases": adv.get("aliases") or [],
            "patched": versions.get("patched") or [],
            "in_cvefixes": bool(ids & known),
        })
    with (OUT / "rustsec_inventory.jsonl").open("w") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    stats = {
        "advisories": len(rows),
        "packages": len(set(r["package"] for r in rows)),
        "in_cvefixes": sum(r["in_cvefixes"] for r in rows),
        "not_in_cvefixes": sum(not r["in_cvefixes"] for r in rows),
        "categories": dict(Counter(c for r in rows for c in r["categories"]).most_common()),
        "with_url": sum(bool(r["url"]) for r in rows),
        "with_patched": sum(bool(r["patched"]) for r in rows),
    }
    (OUT / "rustsec_stats.json").write_text(json.dumps(stats, indent=2) + "\n")
    print(json.dumps(stats, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
