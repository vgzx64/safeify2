"""Apply documented spot-check corrections to the gate-batch labels.

One new Y claim did not survive inspection: the safe pointer cast is shown with
`T: ?Sized` still in scope, which is not a valid thin-pointer cast for an unsized
T.  The fix therefore requires a `Sized` bound (restructuring), so the row is a
conditional replacement (M), not Y.
"""

from __future__ import annotations

import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
OUT = HERE.parent / "out"

CORRECTIONS = [
    {
        "id": "rustsec-issue:RUSTSEC-2021-0144:src/lib.rs:5:0",
        "from": "Y",
        "to": "M",
        "action": "replace",
        "reason": (
            "Spot-check: the new snippet still shows `T: ?Sized` while casting "
            "`*const T`/`*mut T` to `*const ()`/`*mut ()`; that thin-pointer cast "
            "is only valid with a Sized bound, so the safe replacement needs "
            "signature restructuring. Demoted Y -> M."
        ),
    }
]


def main() -> int:
    path = HERE / "reviewed_all.jsonl"
    rows = [json.loads(x) for x in path.open() if x.strip()]
    by_id = {r["id"]: r for r in rows}
    applied = []
    for c in CORRECTIONS:
        r = by_id.get(c["id"])
        if r is None:
            raise SystemExit(f"missing row {c['id']}")
        if r.get("replaceability") != c["from"]:
            raise SystemExit(f"{c['id']} is {r.get('replaceability')}, expected {c['from']}")
        r["replaceability"] = c["to"]
        r["action"] = c["action"]
        r["confidence"] = "medium"
        r["rationale"] = c["reason"]
        r["spotcheck"] = True
        applied.append(c)
    with path.open("w") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    (OUT / "spotcheck_gate.json").write_text(json.dumps(applied, indent=2) + "\n")
    print(json.dumps({"applied": len(applied)}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
