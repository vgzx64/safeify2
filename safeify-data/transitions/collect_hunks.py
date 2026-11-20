"""Collect every CVEfixes diff hunk that changes unsafe code or an unsafe API.

This is the broad inventory, not the curated dataset. It does not require a
parent snapshot, so it includes rows the strict miners could not align. The
LLM adjudication queue is built from these rows.
"""

from __future__ import annotations

import argparse
import json
import re
import sqlite3
from collections import Counter
from pathlib import Path

from extract_candidates import DEFAULT_DB, api_guess, parse_unified_diff, repo_name

OUT = Path(__file__).resolve().parent / "out"


def code_only(text: str) -> str:
    return "\n".join(re.sub(r"//.*$", "", line) for line in text.splitlines())


STRICT_APIS = [
    r"\bptr::copy_nonoverlapping\s*\(",
    r"\bptr::copy\s*\(",
    r"\bptr::read\s*\(",
    r"\bptr::write\s*\(",
    r"\bBox::from_raw\s*\(",
    r"\bVec::from_raw_parts\s*\(",
    r"\bCString::from_raw\s*\(",
    r"\bCStr::from_ptr\s*\(",
    r"\bRc::from_raw\s*\(",
    r"\bArc::from_raw\s*\(",
    r"\bset_len\s*\(",
    r"\bassume_init\s*\(",
    r"\btransmute(?:_copy)?\s*[:(<]",
    r"\bfrom_raw_parts(?:_mut)?\s*\(",
    r"\bget_unchecked(?:_mut)?\s*\(",
    r"\boffset_from\s*\(",
    r"\bPin::new_unchecked\s*\(",
    r"\bunchecked_(?:add|sub|mul)\s*\(",
    r"\bzeroed\s*\(",
    r"\buninitialized\s*\(",
]


def has_code_unsafe(text: str) -> bool:
    body = code_only(text)
    if re.search(r"\bunsafe\s*(?:\{|fn\b|impl\b|trait\b)", body):
        return True
    return any(re.search(p, body) for p in STRICT_APIS)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--db", type=Path, default=DEFAULT_DB)
    ap.add_argument("--out", type=Path, default=OUT)
    args = ap.parse_args()

    con = sqlite3.connect(f"file:{args.db}?mode=ro", uri=True)
    con.row_factory = sqlite3.Row
    commits = {
        str(r["hash"]): (str(r["cve_id"]), r["repo_url"] or "")
        for r in con.execute("select cve_id, hash, repo_url from commits")
    }
    rows = list(
        con.execute(
            "select hash, old_path, new_path, change_type, diff "
            "from file_change where diff is not null and diff != ''"
        )
    )
    con.close()

    seen = set()
    out_rows = []
    stats = Counter()
    by_repo = Counter()
    by_cve = Counter()
    by_api = Counter()
    for r in rows:
        h = str(r["hash"])
        if h not in commits:
            stats["no_commit"] += 1
            continue
        cve, url = commits[h]
        repo = repo_name(url)
        if not repo:
            stats["no_repo"] += 1
            continue
        path = r["old_path"] if r["old_path"] not in (None, "", "nan") else r["new_path"]
        if not path:
            continue
        for i, hunk in enumerate(parse_unified_diff(r["diff"])):
            old = "\n".join(x[1] for x in hunk["deleted"])
            new = "\n".join(x[1] for x in hunk["added"])
            old_u = has_code_unsafe(old)
            new_u = has_code_unsafe(new)
            if not (old_u or new_u):
                continue
            if old_u and not new_u:
                kind = "safe_candidate"
            elif old_u and new_u:
                kind = "unsafe_retained"
            else:
                kind = "unsafe_added"
            key = (h, path, old.strip(), new.strip())
            if key in seen:
                stats["duplicate"] += 1
                continue
            seen.add(key)
            rec = {
                "id": f"hunk:{cve}:{h[:10]}:{path}:{hunk['old_start']}:{i}",
                "source": "cvefixes",
                "cve_id": cve,
                "commit": h,
                "repo_url": url,
                "repo_name": repo,
                "path": path,
                "old_path": r["old_path"],
                "new_path": r["new_path"],
                "change_type": r["change_type"],
                "hunk_index": i,
                "span_start": hunk["old_start"],
                "span_end": hunk["old_end"],
                "kind": kind,
                "old_unsafe": old_u,
                "new_unsafe": new_u,
                "api_old": api_guess(old),
                "api_new": api_guess(new),
                "old_snippet": old,
                "safe_snippet": new,
                "old_lines": len(hunk["deleted"]),
                "new_lines": len(hunk["added"]),
                "review_status": "unreviewed",
                "label": "unreviewed",
            }
            out_rows.append(rec)
            stats[kind] += 1
            by_repo[repo] += 1
            by_cve[cve] += 1
            by_api[rec["api_old"] or rec["api_new"] or "unknown"] += 1

    args.out.mkdir(parents=True, exist_ok=True)
    with (args.out / "all_hunks.jsonl").open("w") as f:
        for rec in out_rows:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    summary = {
        "rows": len(out_rows),
        "kinds": dict(stats),
        "by_repo": dict(by_repo.most_common()),
        "by_cve": dict(by_cve.most_common()),
        "by_api": dict(by_api.most_common()),
    }
    (args.out / "all_hunks_stats.json").write_text(json.dumps(summary, indent=2) + "\n")
    print(json.dumps(summary, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
