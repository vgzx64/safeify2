"""Targeted pattern mining over CVEfixes fix diffs.

This is the expansion pass after the block-level pilot. It finds hunks where a
known unsafe API disappears and a known safe replacement appears, even when the
surrounding `unsafe` block remains. That second case is a conditional/guard
transition, not a fully safe replacement.

Outputs:
    out/pattern_candidates.jsonl
    out/pattern_stats.json
"""

from __future__ import annotations

import argparse
import json
import re
import sqlite3
from collections import Counter
from pathlib import Path

from extract_candidates import (
    DEFAULT_DB,
    DEFAULT_REPOS,
    GitCache,
    lines_match,
    norm,
    parse_unified_diff,
    repo_name,
)

OUT = Path(__file__).resolve().parent / "out"

# (name, old unsafe API, expected safe replacement)
PATTERNS = [
    ("set_len", r"\bset_len\s*\(", r"\b(resize|truncate|clear)\s*\(|vec!\["),
    ("uninit", r"\b(uninitialized|assume_init|zeroed)\b", r"MaybeUninit|\[\s*0|vec!\[0"),
    ("get_unchecked", r"\bget_unchecked(_mut)?\s*\(", r"\.get(_mut)?\s*\(|\[[^\]]+\]"),
    ("from_raw", r"\b(from_raw|from_raw_parts|from_raw_parts_mut|from_ptr)\s*\(", r"\.as_slice|\.as_mut_slice|vec!\[|Box::new|CString::new|Rc::new|Vec::from|&[A-Za-z_]"),
    ("ptr_read", r"\bptr::read\s*\(", r"\.take\s*\(|\.clone\s*\("),
    ("ptr_write", r"\bptr::write\s*\(", r"\.replace\s*\(|\[[^\]]+\]\s*="),
    ("copy", r"\b(copy_nonoverlapping|ptr::copy)\s*\(", r"copy_from_slice|clone_from_slice|\.to_vec\s*\("),
    ("write_bytes", r"\bwrite_bytes\s*\(", r"\.fill\s*\("),
    ("pin", r"\bPin::new_unchecked\s*\(", r"Pin::new\s*\(|Pin::from\s*\("),
    ("transmute", r"\btransmute(_copy)?\s*[::(<]", r"\bas\s+[A-Za-z_]|from_le_bytes|to_le_bytes|from_be_bytes"),
]


UNSAFE_CALLS = [
    r"\bptr::copy_nonoverlapping\s*\(",
    r"\bptr::copy\s*\(",
    r"\bptr::read\s*\(",
    r"\bptr::write\s*\(",
    r"\bget_unchecked(?:_mut)?\s*\(",
    r"\bset_len\s*\(",
    r"\bassume_init\s*\(",
    r"\bfrom_raw_parts(?:_mut)?\s*\(",
    r"\btransmute(?:_copy)?\s*[:(<]",
    r"\bzeroed\s*\(",
    r"\buninitialized\s*\(",
    r"\bPin::new_unchecked\s*\(",
]


def code_only(text: str) -> str:
    return "\n".join(re.sub(r"//.*$", "", line) for line in text.splitlines())


def focus(lines: list[str], regex: str, context: int = 3) -> str:
    idx = [i for i, line in enumerate(lines) if re.search(regex, code_only(line))]
    if not idx:
        return ""
    lo = max(0, min(idx) - context)
    hi = min(len(lines), max(idx) + context + 1)
    return "\n".join(lines[lo:hi])


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
    ap.add_argument("--max-lines", type=int, default=35)
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
    changes = list(
        con.execute(
            "select hash, old_path, new_path, change_type, diff from file_change "
            "where diff is not null and diff != ''"
        )
    )
    con.close()

    git = GitCache(args.repos)
    args.out.mkdir(parents=True, exist_ok=True)
    rows: list[dict] = []
    stats = Counter()
    rejects = Counter()
    by_pattern = Counter()
    by_repo = Counter()
    by_cve = Counter()

    for r in changes:
        h = str(r["hash"])
        if h not in commits:
            rejects["no_commit"] += 1
            continue
        cve, url = commits[h]
        repo = repo_name(url)
        if not repo:
            rejects["no_repo"] += 1
            continue
        if r["old_path"] in (None, "", "nan") or r["new_path"] in (None, "", "nan"):
            rejects["deleted_or_bad_path"] += 1
            continue
        path = r["old_path"]
        parent = parents.get(h) or git.parent(repo, h)
        if not parent:
            rejects["no_parent"] += 1
            continue
        before_path = git.resolve_path(repo, parent, path) or path
        after_path = git.resolve_path(repo, h, r["new_path"]) or r["new_path"]
        before = git.file(repo, parent, before_path)
        after = git.file(repo, h, after_path)
        if before is None or after is None:
            rejects["missing_snapshot"] += 1
            continue

        for hunk in parse_unified_diff(r["diff"]):
            deleted = hunk["deleted"]
            added = hunk["added"]
            if not deleted or not added:
                continue
            dt = "\n".join(x[1] for x in deleted)
            at = "\n".join(x[1] for x in added)
            dcode, acode = code_only(dt), code_only(at)
            if len(deleted) > args.max_lines or len(added) > args.max_lines:
                rejects["hunk_too_large"] += 1
                continue
            for name, old_pat, new_pat in PATTERNS:
                if not re.search(old_pat, dcode):
                    continue
                if re.search(old_pat, acode):
                    continue
                if not re.search(new_pat, acode):
                    continue
                old_focus = focus([x[1] for x in deleted], old_pat)
                if not old_focus:
                    continue
                if not lines_match(before, deleted):
                    rejects["not_in_before"] += 1
                    continue
                if not lines_match(after, added):
                    rejects["not_in_after"] += 1
                    continue
                residual = bool(
                    re.search(r"\bunsafe\s*(?:\{|fn\b|impl\b|trait\b)", acode)
                    or any(re.search(p, acode) for p in UNSAFE_CALLS)
                )
                kind = "pattern_conditional" if residual else "pattern_safe"
                rec = {
                    "id": f"cvefixes-pattern:{cve}:{h[:10]}:{path}:{hunk['old_start']}-{hunk['old_end']}:{name}",
                    "source": "cvefixes",
                    "method": "pattern",
                    "cve_id": cve,
                    "commit": h,
                    "parent_commit": parent,
                    "repo_url": url,
                    "repo_name": repo,
                    "path": path,
                    "resolved_path": before_path if before_path == after_path else None,
                    "fn_id": fn_guess(before, hunk["old_start"]),
                    "span_start": hunk["old_start"],
                    "span_end": hunk["old_end"],
                    "pattern": name,
                    "api_guess": name,
                    "old_snippet": old_focus,
                    "safe_snippet": at,
                    "residual_unsafe": residual,
                    "candidate_type": kind,
                    "observed": "safe" if not residual else "conditional",
                    "replaceability": "unassigned",
                    "action": "unassigned",
                    "scope": "hunk",
                    "split": "unassigned",
                }
                rows.append(rec)
                stats[kind] += 1
                by_pattern[name] += 1
                by_repo[repo] += 1
                by_cve[cve] += 1

    with (args.out / "pattern_candidates.jsonl").open("w") as f:
        for rec in rows:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    summary = {
        "rows": len(rows),
        "types": dict(stats),
        "by_pattern": dict(by_pattern.most_common()),
        "by_repo": dict(by_repo.most_common()),
        "by_cve": dict(by_cve.most_common()),
        "rejects": dict(rejects),
    }
    (args.out / "pattern_stats.json").write_text(json.dumps(summary, indent=2) + "\n")
    print(json.dumps(summary, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
