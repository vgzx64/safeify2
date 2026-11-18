"""Reviewer corrections that override the first-annotator labels.

Written by the spot-check review passes. Applied by rebuild_v01 and
build_family_core so every rebuild is reproducible. A correction of `U`
drops the row from the dataset (it was not decidable).
"""

from __future__ import annotations

import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
PATH = HERE / "adjudication" / "corrections.jsonl"


def load() -> dict[str, dict]:
    if not PATH.exists():
        return {}
    out = {}
    for line in PATH.open():
        if line.strip():
            r = json.loads(line)
            out[r["id"]] = r
    return out


def apply(rows: list[dict]) -> list[dict]:
    """Patch rows in place by id; return rows with `U` corrections removed."""
    corr = load()
    kept = []
    for r in rows:
        c = corr.get(r.get("id"))
        if c:
            r["replaceability"] = c["replaceability"]
            if c.get("action"):
                r["action"] = c["action"]
            r["label"] = c["replaceability"]
            r["corrected_by"] = c.get("spot_check", "spot-check")
            r["correction_reason"] = c.get("reason", "")
        if r.get("replaceability") == "U":
            continue
        kept.append(r)
    return kept
