"""Extract block-level unsafe-to-safe transition candidates from CVEfixes.db.

This is a new analysis, not the RQ4 notebook. The unit is a vulnerable
``unsafe_block`` row whose exact block is absent from ``unsafe_block_fix`` while
its function still exists. Every candidate is checked against the real parent
and fix snapshots from ``repos_mirror`` and against the fix commit's diff.

Usage (from repo root):
    python research/transitions/extract_candidates.py --limit 20
    python research/transitions/extract_candidates.py

Outputs:
    research/transitions/out/candidates.jsonl
    research/transitions/out/rejects.jsonl
    research/transitions/out/stats.json
"""

from __future__ import annotations

import argparse
import json
import re
import sqlite3
import subprocess
import sys
from collections import Counter, defaultdict
from pathlib import Path

DEFAULT_DB = Path("/mnt/tc2015_p5/Code/rust_ecosystem/CVEfixes.db")
DEFAULT_REPOS = Path("/mnt/tc2015_p5/Code/rust_ecosystem/repos_mirror")
OUT = Path(__file__).resolve().parent / "out"

API_PATTERNS = [
    ("ptr::copy_nonoverlapping", r"\bcopy_nonoverlapping\s*\("),
    ("ptr::copy", r"\bptr::copy\s*\("),
    ("ptr::read", r"\bptr::read\s*\("),
    ("ptr::write_bytes", r"\bptr::write_bytes\s*\("),
    ("ptr::write", r"\bptr::write\s*\("),
    ("ptr::deref", r"\*\s*[A-Za-z_][A-Za-z0-9_]*"),
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
    ("as_ref", r"\.as_ref\s*\("),
    ("Pin::new_unchecked", r"\bPin::new_unchecked\s*\("),
    ("unchecked_add", r"\bunchecked_add\s*\("),
    ("unchecked_mul", r"\bunchecked_mul\s*\("),
    ("unwrap_unchecked", r"\bunwrap_unchecked\s*\("),
    ("zeroed", r"\bzeroed\s*\("),
    ("uninitialized", r"\buninitialized\s*\("),
]


def repo_name(url: str | None) -> str:
    if not url:
        return ""
    m = re.search(
        r"https?://(?:[^/]+\.)*[^/]+/([^/]+)/([^/]+?)(?:\.git)?"
        r"(?:/(?:pull|issues|merge_requests|commit|tree|blob)/.*)?/?$",
        url,
    )
    if m:
        return f"{m.group(1)}_{m.group(2)}"
    parts = url.rstrip("/").rsplit("/", 2)
    if len(parts) >= 3:
        return f"{parts[1]}_{parts[2].replace('.git', '')}"
    return ""


def norm(text: str) -> str:
    return "\n".join(
        " ".join(line.split()) for line in text.splitlines() if line.strip()
    )


def lines_match(text: str, numbered: list[tuple[int, str]], threshold: float = 0.8) -> bool:
    """Check that diff lines occur at their expected line numbers.

    Deleted lines in a hunk are not necessarily contiguous in the parent file,
    so substring matching on the joined text produces false negatives.
    """
    lines = text.splitlines()
    total = good = 0
    for lineno, content in numbered:
        if not content.strip():
            continue
        total += 1
        i = lineno - 1
        if 0 <= i < len(lines) and lines[i].strip() == content.strip():
            good += 1
    return total > 0 and (good / total) >= threshold


def api_guess(snippet: str) -> str:
    for name, pat in API_PATTERNS:
        if re.search(pat, snippet):
            return name
    return ""


def parse_unified_diff(diff: str) -> list[dict]:
    """Return hunks with old/new line ranges and deleted/added lines."""
    hunks: list[dict] = []
    cur: dict | None = None
    old_line = new_line = 0
    header = re.compile(r"^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@")
    for raw in diff.splitlines():
        m = header.match(raw)
        if m:
            old_start = int(m.group(1))
            old_len = int(m.group(2) or 1)
            new_start = int(m.group(3))
            new_len = int(m.group(4) or 1)
            cur = {
                "old_start": old_start,
                "old_end": old_start + max(old_len, 1) - 1,
                "new_start": new_start,
                "new_end": new_start + max(new_len, 1) - 1,
                "deleted": [],
                "added": [],
            }
            hunks.append(cur)
            old_line, new_line = old_start, new_start
            continue
        if cur is None:
            continue
        if raw.startswith("---") or raw.startswith("+++"):
            continue
        if raw.startswith("-"):
            cur["deleted"].append((old_line, raw[1:]))
            old_line += 1
        elif raw.startswith("+"):
            cur["added"].append((new_line, raw[1:]))
            new_line += 1
        elif raw.startswith(" "):
            old_line += 1
            new_line += 1
        # "\ No newline at end of file" ignored
    return hunks


class GitCache:
    def __init__(self, repos: Path) -> None:
        self.repos = repos
        self.parents: dict[tuple[str, str], str | None] = {}
        self.files: dict[tuple[str, str, str], str | None] = {}
        self.trees: dict[tuple[str, str], list[str]] = {}

    def repo_path(self, repo: str) -> Path | None:
        for base in (self.repos, self.repos.parent / "repos_worktree"):
            p = base / repo
            if p.exists():
                return p
        return None

    def run(self, repo: str, *args: str) -> str | None:
        p = self.repo_path(repo)
        if p is None:
            return None
        try:
            r = subprocess.run(
                ["git", "-C", str(p), *args],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=30,
            )
        except (OSError, subprocess.TimeoutExpired):
            return None
        return r.stdout if r.returncode == 0 else None

    def parent(self, repo: str, commit: str) -> str | None:
        key = (repo, commit)
        if key not in self.parents:
            out = self.run(repo, "rev-parse", f"{commit}^")
            self.parents[key] = out.strip() if out else None
        return self.parents[key]

    def file(self, repo: str, rev: str, path: str) -> str | None:
        key = (repo, rev, path)
        if key not in self.files:
            out = self.run(repo, "show", f"{rev}:{path}")
            self.files[key] = out
        return self.files[key]

    def resolve_path(self, repo: str, rev: str, path: str) -> str | None:
        """Return an exact repo-relative path, or a unique path suffix match.

        CVEfixes paths are sometimes relative to a workspace member, not the
        repository root (e.g. ``src/lib.rs`` vs ``bcrypt/src/lib.rs``).
        """
        if self.file(repo, rev, path) is not None:
            return path
        key = (repo, rev)
        if key not in self.trees:
            out = self.run(repo, "ls-tree", "-r", "--name-only", rev)
            self.trees[key] = out.splitlines() if out else []
        matches = [
            p for p in self.trees[key]
            if p == path or p.endswith("/" + path)
        ]
        return matches[0] if len(matches) == 1 else None


def load_db(db: Path):
    con = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    con.row_factory = sqlite3.Row

    commits = {}
    for r in con.execute("select cve_id, hash, repo_url from commits"):
        commits[str(r["hash"])] = (str(r["cve_id"]), r["repo_url"] or "")

    parents = {}
    for r in con.execute("select hash, parents from ext_commits"):
        p = (r["parents"] or "").strip()
        if p and p.lower() != "none":
            parents[str(r["hash"])] = p

    changes: dict[tuple[str, str], dict] = {}
    for r in con.execute(
        "select hash, old_path, new_path, change_type, diff from file_change"
    ):
        rec = {
            "hash": str(r["hash"]),
            "old_path": r["old_path"],
            "new_path": r["new_path"],
            "change_type": r["change_type"],
            "diff": r["diff"] or "",
        }
        for p in (r["old_path"], r["new_path"]):
            if p:
                changes[(str(r["hash"]), p)] = rec

    vuln = [
        dict(r)
        for r in con.execute(
            "select distinct cve_id, hash, fn_id, path, span_start, span_end from unsafe_block"
        )
    ]
    fixed = {
        (
            str(r["cve_id"]),
            str(r["hash"]),
            r["fn_id"],
            r["path"],
            str(r["span_start"]),
            str(r["span_end"]),
        )
        for r in con.execute(
            "select distinct cve_id, hash, fn_id, path, span_start, span_end from unsafe_block_fix"
        )
    }
    fixed_fns = {
        (str(r["cve_id"]), str(r["hash"]), r["fn_id"], r["path"])
        for r in con.execute(
            "select distinct cve_id, hash, fn_id, path from unsafe_block_fix"
        )
    }
    con.close()
    return commits, parents, changes, vuln, fixed, fixed_fns


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--db", type=Path, default=DEFAULT_DB)
    ap.add_argument("--repos", type=Path, default=DEFAULT_REPOS)
    ap.add_argument("--out", type=Path, default=OUT)
    ap.add_argument("--limit", type=int, default=0)
    args = ap.parse_args()

    commits, parents, changes, vuln, fixed, fixed_fns = load_db(args.db)
    git = GitCache(args.repos)
    args.out.mkdir(parents=True, exist_ok=True)

    stats = Counter()
    reasons = Counter()
    by_api = Counter()
    by_cve = Counter()
    by_repo = Counter()
    type_counts = Counter()
    seen_files = Counter()
    candidates: list[dict] = []
    rejects: list[dict] = []

    for row in vuln:
        cve = str(row["cve_id"])
        h = str(row["hash"])
        fn = row["fn_id"]
        path = row["path"]
        s, e = str(row["span_start"]), str(row["span_end"])
        key = (cve, h, fn, path, s, e)
        if key in fixed:
            continue
        if (cve, h, fn, path) not in fixed_fns:
            reasons["function_removed_or_not_analyzed"] += 1
            continue
        if h not in commits:
            reasons["no_commit_row"] += 1
            continue
        cve2, url = commits[h]
        repo = repo_name(url)
        if not repo:
            reasons["no_repo_name"] += 1
            continue
        parent = parents.get(h) or git.parent(repo, h)
        if not parent:
            reasons["no_parent"] += 1
            continue
        before_path = git.resolve_path(repo, parent, path) or path
        after_path = git.resolve_path(repo, h, path) or path
        before = git.file(repo, parent, before_path)
        after = git.file(repo, h, after_path)
        if before is None or after is None:
            reasons["missing_before_or_after"] += 1
            continue
        lines_before = before.splitlines()
        lines_after = after.splitlines()
        try:
            old = "\n".join(lines_before[int(s) - 1:int(e)])
        except (ValueError, IndexError):
            reasons["bad_span"] += 1
            continue
        if not old.strip():
            reasons["empty_old_snippet"] += 1
            continue
        # Content check: a block whose text is still present is retained, even
        # if the analyzer's span moved.
        if norm(old) in norm(after):
            reasons["retained_text"] += 1
            continue
        # Function must still exist in the fixed file.
        short_fn = fn.split("::")[-1] if fn else ""
        if short_fn and not re.search(r"\bfn\s+" + re.escape(short_fn) + r"\b", after):
            reasons["function_gone_from_file"] += 1
            continue
        ch = changes.get((h, path))
        if not ch or not ch["diff"]:
            reasons["no_diff"] += 1
            continue
        hunks = parse_unified_diff(ch["diff"])
        hit = [
            x
            for x in hunks
            if int(s) <= x["old_end"] and int(e) >= x["old_start"]
        ]
        if not hit:
            reasons["no_overlapping_hunk"] += 1
            continue
        deleted = [line for x in hit for _, line in x["deleted"]]
        added = [line for x in hit for _, line in x["added"]]
        if not deleted:
            reasons["no_deleted_lines"] += 1
            continue
        if norm(old) not in norm("\n".join(deleted)):
            reasons["old_block_not_fully_deleted"] += 1
            continue
        safe = "\n".join(added)
        if not safe.strip():
            kind = "removed"
        elif re.search(r"\bunsafe\b", safe):
            kind = "replaced_unsafe"
        else:
            kind = "replaced_safe"
        rec = {
            "id": f"cvefixes:{cve}:{h[:10]}:{fn}:{s}-{e}",
            "source": "cvefixes",
            "cve_id": cve,
            "commit": h,
            "parent_commit": parent,
            "repo_url": url,
            "repo_name": repo,
            "path": path,
            "resolved_path": before_path if before_path == after_path else None,
            "fn_id": fn,
            "span_start": int(s),
            "span_end": int(e),
            "api_guess": api_guess(old),
            "old_snippet": old,
            "safe_snippet": safe,
            "deleted_lines": deleted,
            "added_lines": added,
            "change_type": ch["change_type"],
            "candidate_type": kind,
            "replaceability": "unassigned",
            "action": "unassigned",
            "scope": "block",
            "split": "unassigned",
        }
        candidates.append(rec)
        type_counts[kind] += 1
        by_api[rec["api_guess"] or "unknown"] += 1
        by_cve[cve] += 1
        by_repo[repo] += 1
        seen_files[path] += 1
        if args.limit and len(candidates) >= args.limit:
            break

    # Write outputs
    with (args.out / "candidates.jsonl").open("w") as f:
        for r in candidates:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    with (args.out / "rejects.jsonl").open("w") as f:
        for r in rejects:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")

    out = {
        "db": str(args.db),
        "vuln_blocks": len(vuln),
        "fixed_blocks": len(fixed),
        "candidates": len(candidates),
        "candidate_types": dict(type_counts),
        "rejects": dict(reasons),
        "by_api": dict(by_api.most_common()),
        "by_cve": dict(by_cve.most_common()),
        "by_repo": dict(by_repo.most_common()),
        "top_files": dict(seen_files.most_common(20)),
        "limited": bool(args.limit),
    }
    (args.out / "stats.json").write_text(json.dumps(out, indent=2) + "\n")
    print(json.dumps(out, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
