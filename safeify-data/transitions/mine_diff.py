"""Mine unsafe transitions directly from CVEfixes fix diffs.

The analyzer-based extractor (``extract_candidates.py``) only sees blocks the
rust-analyzer run recorded. This script starts from the fix diff instead, so it
can find safe replacements even when the analyzer span moved, the block was not
recorded, or the project failed to analyze.

It classifies each eligible hunk as:
  - ``diff_safe``    deleted code has unsafe; added code has no unsafe
  - ``diff_unsafe``  deleted and added code both have unsafe
  - ``diff_removed`` unsafe code was deleted with no replacement

Usage:
    python mine_diff.py
"""

from __future__ import annotations

import argparse
import json
import re
import sqlite3
import subprocess
from collections import Counter
from pathlib import Path

from extract_candidates import (
    DEFAULT_DB,
    DEFAULT_REPOS,
    GitCache,
    api_guess,
    lines_match,
    norm,
    parse_unified_diff,
    repo_name,
)

OUT = Path(__file__).resolve().parent / "out"
HEADER = re.compile(r"^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@")


def code_only(text: str) -> str:
    """Drop // comments; enough for the unsafe-keyword filters used here."""
    return "\n".join(re.sub(r"//.*$", "", line) for line in text.splitlines())


STRICT_APIS = [
    ("ptr::copy_nonoverlapping", r"\bcopy_nonoverlapping\s*\("),
    ("ptr::copy", r"\bptr::copy\s*\("),
    ("ptr::read", r"\bptr::read\s*\("),
    ("ptr::write_bytes", r"\bptr::write_bytes\s*\("),
    ("ptr::write", r"\bptr::write\s*\("),
    ("Box::from_raw", r"\bBox::from_raw\s*\("),
    ("Vec::from_raw_parts", r"\bVec::from_raw_parts\s*\("),
    ("CString::from_raw", r"\bCString::from_raw\s*\("),
    ("CStr::from_ptr", r"\bCStr::from_ptr\s*\("),
    ("Rc::from_raw", r"\bRc::from_raw\s*\("),
    ("Arc::from_raw", r"\bArc::from_raw\s*\("),
    ("set_len", r"\bset_len\s*\("),
    ("assume_init", r"\bassume_init\s*\("),
    ("transmute_copy", r"\btransmute_copy\s*\("),
    ("transmute", r"\btransmute\s*[::(<]"),
    ("from_raw_parts_mut", r"\bfrom_raw_parts_mut\s*\("),
    ("from_raw_parts", r"\bfrom_raw_parts\s*\("),
    ("get_unchecked_mut", r"\bget_unchecked_mut\s*\("),
    ("get_unchecked", r"\bget_unchecked\s*\("),
    ("offset_from", r"\boffset_from\s*\("),
    ("Pin::new_unchecked", r"\bPin::new_unchecked\s*\("),
    ("unchecked_add", r"\bunchecked_add\s*\("),
    ("unchecked_mul", r"\bunchecked_mul\s*\("),
    ("unwrap_unchecked", r"\bunwrap_unchecked\s*\("),
    ("zeroed", r"\bzeroed\s*\("),
    ("uninitialized", r"\buninitialized\s*\("),
]


def has_code_unsafe(text: str) -> bool:
    body = code_only(text)
    if re.search(r"\bunsafe\s*(?:\{|fn\b|impl\b|trait\b)", body):
        return True
    return any(re.search(pat, body) for _, pat in STRICT_APIS)


def unsafe_focus(deleted: list[tuple[int, str]], context: int = 4) -> str:
    idxs = [
        i
        for i, (_, text) in enumerate(deleted)
        if has_code_unsafe(text) or re.search(r"\bunsafe\b", code_only(text))
    ]
    if not idxs:
        return ""
    lo = max(0, min(idxs) - context)
    hi = min(len(deleted), max(idxs) + context + 1)
    return "\n".join(text for _, text in deleted[lo:hi])


def fn_guess(before: str, line: int) -> str:
    lines = before.splitlines()
    for i in range(min(line, len(lines)) - 1, -1, -1):
        m = re.search(
            r"^\s*(?:pub(?:\([^)]*\))?\s+)?(?:async\s+)?(?:unsafe\s+)?fn\s+([A-Za-z_][A-Za-z0-9_]*)",
            lines[i],
        )
        if m:
            return m.group(1)
    return ""


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--db", type=Path, default=DEFAULT_DB)
    ap.add_argument("--repos", type=Path, default=DEFAULT_REPOS)
    ap.add_argument("--out", type=Path, default=OUT)
    ap.add_argument("--max-lines", type=int, default=30)
    args = ap.parse_args()

    con = sqlite3.connect(f"file:{args.db}?mode=ro", uri=True)
    con.row_factory = sqlite3.Row
    commits = {
        str(r["hash"]): (str(r["cve_id"]), r["repo_url"] or "")
        for r in con.execute("select cve_id, hash, repo_url from commits")
    }
    parents = {}
    for r in con.execute("select hash, parents from ext_commits"):
        p = (r["parents"] or "").strip()
        if p and p.lower() != "none":
            parents[str(r["hash"])] = p
    rows = list(
        con.execute(
            "select hash, old_path, new_path, change_type, diff "
            "from file_change where diff is not null and diff != ''"
        )
    )
    con.close()

    git = GitCache(args.repos)
    args.out.mkdir(parents=True, exist_ok=True)
    stats = Counter()
    reject = Counter()
    by_repo = Counter()
    by_cve = Counter()
    by_api = Counter()
    out_rows: list[dict] = []

    for r in rows:
        h = str(r["hash"])
        if h not in commits:
            reject["no_commit_row"] += 1
            continue
        cve, url = commits[h]
        repo = repo_name(url)
        if not repo:
            reject["no_repo_name"] += 1
            continue
        if r["old_path"] in (None, "", "nan") or r["new_path"] in (None, "", "nan"):
            reject["deleted_or_bad_path"] += 1
            continue
        path = r["old_path"]
        parent = parents.get(h) or git.parent(repo, h)
        if not parent:
            reject["no_parent"] += 1
            continue
        before_path = git.resolve_path(repo, parent, path) or path
        after_path = git.resolve_path(repo, h, r["new_path"]) or r["new_path"]
        before = git.file(repo, parent, before_path)
        after = git.file(repo, h, after_path)
        if before is None or after is None:
            reject["missing_before_or_after"] += 1
            continue

        for hunk in parse_unified_diff(r["diff"]):
            deleted = hunk["deleted"]
            added = hunk["added"]
            if not deleted:
                continue
            dt = "\n".join(x[1] for x in deleted)
            at = "\n".join(x[1] for x in added)
            focus = unsafe_focus(deleted)
            if not focus or not has_code_unsafe(focus):
                continue
            if len(focus.splitlines()) > args.max_lines or len(added) > args.max_lines:
                reject["hunk_too_large"] += 1
                continue
            if len(code_only(focus).strip()) < 8:
                reject["deleted_too_short"] += 1
                continue
            if added and len(code_only(at).strip()) < 8:
                reject["added_too_short"] += 1
                continue
            if not lines_match(before, deleted):
                reject["not_in_before"] += 1
                continue
            if added and not lines_match(after, added):
                reject["not_in_after"] += 1
                continue
            unsafe_added = has_code_unsafe(at) if at.strip() else False
            if not added:
                kind = "diff_removed"
            elif unsafe_added:
                kind = "diff_unsafe"
            else:
                kind = "diff_safe"

            fn = fn_guess(before, hunk["old_start"])
            rec = {
                "id": f"cvefixes-diff:{cve}:{h[:10]}:{path}:{hunk['old_start']}-{hunk['old_end']}",
                "source": "cvefixes",
                "method": "diff",
                "cve_id": cve,
                "commit": h,
                "parent_commit": parent,
                "repo_url": url,
                "repo_name": repo,
                "path": path,
                "resolved_path": before_path if before_path == after_path else None,
                "fn_id": fn,
                "span_start": hunk["old_start"],
                "span_end": hunk["old_end"],
                "api_guess": api_guess(focus),
                "old_snippet": focus,
                "safe_snippet": at,
                "candidate_type": kind,
                "change_type": r["change_type"],
                "replaceability": "unassigned",
                "action": "unassigned",
                "scope": "hunk",
                "split": "unassigned",
            }
            out_rows.append(rec)
            stats[kind] += 1
            by_repo[repo] += 1
            by_cve[cve] += 1
            by_api[rec["api_guess"] or "unknown"] += 1

    with (args.out / "diff_candidates.jsonl").open("w") as f:
        for rec in out_rows:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    summary = {
        "rows": len(out_rows),
        "types": dict(stats),
        "rejects": dict(reject),
        "by_repo": dict(by_repo.most_common()),
        "by_cve": dict(by_cve.most_common()),
        "by_api": dict(by_api.most_common()),
    }
    (args.out / "diff_stats.json").write_text(json.dumps(summary, indent=2) + "\n")
    print(json.dumps(summary, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
