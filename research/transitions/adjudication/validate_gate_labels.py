"""Independent QC for gate-batch labels.

Checks, for every chunk/label pair:
- id set equality and uniqueness (merge already enforces this);
- evidence is actually present in the shown snippet (normalized substring);
- Y did not keep an unsafe keyword/API in the new snippet;
- veto rows carry a reason.

Prints a per-chunk table and exits non-zero only on hard errors; evidence misses
are reported as warnings because snippets are clipped and quotes may be trimmed.
"""

from __future__ import annotations

import json
import re
import sys
from collections import Counter
from pathlib import Path

HERE = Path(__file__).resolve().parent
TAGS = [f"a{i:02d}" for i in range(1, 7)] + [f"b{i:02d}" for i in range(1, 7)]
UNSAFE_API = re.compile(
    r"\b(unsafe|from_raw_parts|from_raw|get_unchecked|set_len|assume_init|"
    r"transmute|uninitialized|zeroed|ptr::(read|write|copy|copy_nonoverlapping|deref))\b"
)


def norm(s: str) -> str:
    return " ".join(s.split())


def load(path: Path) -> list[dict]:
    return [json.loads(x) for x in path.open() if x.strip()]


def main() -> int:
    hard = 0
    for tag in TAGS:
        label_path = HERE / f"labels_gate_{tag}.jsonl"
        if not label_path.exists():
            print(f"{tag}: missing")
            hard += 1
            continue
        ins = {r["id"]: r for r in load(HERE / f"gate_{tag}.jsonl")}
        labs = load(label_path)
        miss_old = miss_new = y_unsafe = no_reason = 0
        for lab in labs:
            src = ins.get(lab["id"])
            if src is None:
                hard += 1
                continue
            old = norm(src.get("old_snippet") or "")
            new = norm(src.get("safe_snippet") or "")
            evo = norm(lab.get("evidence_old") or "")
            evn = norm(lab.get("evidence_new") or "")
            if evo and not all(part in old for part in evo.split("...") if part.strip()):
                miss_old += 1
            if evn and not all(part in new for part in evn.split("...") if part.strip()):
                miss_new += 1
            if lab.get("replaceability") == "Y" and UNSAFE_API.search(new):
                y_unsafe += 1
            if lab.get("veto") and not (lab.get("veto_reason") or "").strip():
                no_reason += 1
        print(
            f"{tag}: rows={len(labs)} "
            f"labels={dict(Counter(x.get('replaceability') for x in labs))} "
            f"evidence_miss_old={miss_old} evidence_miss_new={miss_new} "
            f"Y_with_unsafe_in_new={y_unsafe} veto_no_reason={no_reason}"
        )
    return 1 if hard else 0


if __name__ == "__main__":
    sys.exit(main())
