"""Verify unsafe_block / unsafe_block_fix span semantics + diff-hunk matching.

1) unsafe_block spans index the PRE-fix file; unsafe_block_fix spans index the
   POST-fix file. Both should contain 'unsafe'.
2) For RQ4 positives, the diff hunk whose '-' side covers the block line range
   gives the safe '+' counterpart.
"""
import csv
import os
import re
import sqlite3
import subprocess
from collections import Counter

DB = "/home/dev2/Code/safeify2/research/rust_ecosystem/CVEfixes.db"
RQ4 = ("/home/dev2/Code/safeify2/research/rust_ecosystem/"
       "rq4_block_conversion_manifest.csv")
WT = "/home/dev2/Code/safeify2/research/rust_ecosystem/repos_mirror"


def repo_dir(url):
    m = re.search(r"github\.com/([^/]+/[^/]+?)(\.git)?/?$", url or "")
    if not m:
        return None
    d = os.path.join(WT, m.group(1).replace("/", "_"))
    return d if os.path.isdir(d) else None


def show(wt, rev, path):
    r = subprocess.run(["git", "-C", wt, "show", f"{rev}:{path}"],
                       capture_output=True, text=True, timeout=60)
    return r.stdout if r.returncode == 0 else None


def seg(lines, s, e):
    try:
        s, e = int(s), int(e)
    except (TypeError, ValueError):
        return ""
    if s < 1 or e < s or s > len(lines):
        return ""
    return "\n".join(lines[s - 1:e])


HUNK_RX = re.compile(r"^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@")


def hunk_for_line(diff, line):
    """Return (minus_lines, plus_lines) of the hunk covering pre-file `line`."""
    cur = None
    minus, plus = [], []
    for ln in (diff or "").splitlines():
        m = HUNK_RX.match(ln)
        if m:
            if cur is not None and cur[0] <= line <= cur[1]:
                return minus, plus
            start = int(m.group(1))
            cnt = int(m.group(2) or 1)
            cur = (start, start + cnt - 1)
            minus, plus = [], []
            continue
        if cur is None:
            continue
        if ln.startswith("-"):
            minus.append(ln[1:])
        elif ln.startswith("+"):
            plus.append(ln[1:])
        elif ln.startswith(" "):
            minus.append(ln[1:])
            plus.append(ln[1:])
    if cur is not None and cur[0] <= line <= cur[1]:
        return minus, plus
    return None, None


def main():
    db = sqlite3.connect("file:%s?mode=ro" % DB, uri=True)

    # --- 1) unsafe_block / unsafe_block_fix span semantics ---
    st = Counter()
    rows = db.execute(
        "select b.cve_id,b.hash,b.fn_id,b.path,b.span_start,b.span_end "
        "from unsafe_block b join unsafe_block_fix f "
        "on b.cve_id=f.cve_id and b.hash=f.hash and b.fn_id=f.fn_id "
        "and b.path=f.path group by 1,2,3,4 limit 60").fetchall()
    for cve, h, fn_id, path, s, e in rows:
        par = db.execute("select parents from ext_commits where hash=?",
                         (h,)).fetchone()
        if not par or not par[0]:
            st["no_parent"] += 1
            continue
        url = db.execute("select repo_url from commit_life_spans where cve_id=?",
                         (cve,)).fetchone()
        wt = repo_dir(url[0]) if url else None
        if not wt:
            st["no_worktree"] += 1
            continue
        pre = show(wt, par[0].split()[0], path)
        post = show(wt, h, path)
        if not pre or not post:
            st["no_file"] += 1
            continue
        frow = db.execute(
            "select span_start,span_end from unsafe_block_fix where cve_id=? "
            "and hash=? and fn_id=? and path=?", (cve, h, fn_id, path)).fetchone()
        pseg = seg(pre.splitlines(), s, e)
        qseg = seg(post.splitlines(), *frow)
        st["checked"] += 1
        if "unsafe" in pseg:
            st["pre_unsafe"] += 1
        if "unsafe" in qseg:
            st["post_unsafe"] += 1
        if "unsafe" in pseg and "unsafe" in qseg:
            st["both_unsafe"] += 1
    print("unsafe_block spans:", dict(st))

    # --- 2) diff hunk matching for RQ4 positives ---
    h = Counter()
    rq4 = [r for r in csv.DictReader(open(RQ4, encoding="utf-8"))
           if r.get("converted_to_safe") == "1"
           and r.get("verified_conversion") == "1"]
    for r in rq4:
        cve, hsh, path = r["cve_id"], r["hash"], r["path"]
        d = db.execute("select diff from file_change where hash=? and "
                       "(new_path=? or old_path=?)", (hsh, path, path)).fetchone()
        if not d or not d[0]:
            h["no_diff"] += 1
            continue
        minus, plus = hunk_for_line(d[0], int(r["span_start"]))
        if minus is None:
            h["no_hunk"] += 1
            continue
        h["matched"] += 1
        if any("unsafe" in x for x in minus):
            h["minus_has_unsafe"] += 1
        if plus and not any("unsafe" in x for x in plus):
            h["plus_safe"] += 1
    print("diff hunk:", dict(h))


if __name__ == "__main__":
    main()
