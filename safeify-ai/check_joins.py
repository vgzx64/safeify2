"""Verify the pre/post joins needed by cve_pairs.py.

A) RQ4 verified rows: (cve,hash,path,fn) present in `function` (pre) and
   `function_fix` (post)?  Does the pre function contain unsafe and the post
   one not?
B) Surviving blocks: (cve,hash,fn_id,path) present in BOTH `unsafe_block`
   (pre) and `unsafe_block_fix` (post) -> unsafe survives the fix.
"""
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


def main():
    import csv
    db = sqlite3.connect("file:%s?mode=ro" % DB, uri=True)

    # --- A: RQ4 positives ---
    rows = [r for r in csv.DictReader(open(RQ4, encoding="utf-8"))
            if r.get("converted_to_safe") == "1"
            and r.get("verified_conversion") == "1"]
    a = Counter()
    for r in rows:
        cve, h, path = r["cve_id"], r["hash"], r["path"]
        short = r["fn_id"].split("::")[-1]
        pre_row = db.execute(
            "select span_start,span_end from function where cve_id=? and hash=? "
            "and path=? and name=?", (cve, h, path, short)).fetchone()
        post_row = db.execute(
            "select span_start,span_end from function_fix where cve_id=? "
            "and hash=? and path=? and name=?", (cve, h, path, short)).fetchone()
        if not pre_row or not post_row:
            a["no_fn_row"] += 1
            continue
        a["joined"] += 1
        par = db.execute("select parents from ext_commits where hash=?",
                         (h,)).fetchone()
        if not par or not par[0]:
            a["no_parent"] += 1
            continue
        wt = repo_dir(r["repo_url"])
        if not wt:
            a["no_worktree"] += 1
            continue
        pre = show(wt, par[0].split()[0], path)
        post = show(wt, h, path)
        if not pre or not post:
            a["no_file"] += 1
            continue
        ptext = seg(pre.splitlines(), *pre_row)
        qtext = seg(post.splitlines(), *post_row)
        a["checked"] += 1
        if "unsafe" in ptext and "unsafe" not in qtext:
            a["pre_unsafe_post_safe"] += 1
        elif "unsafe" in ptext and "unsafe" in qtext:
            a["both_unsafe"] += 1
        elif "unsafe" not in ptext:
            a["pre_safe"] += 1

    # --- B: surviving blocks ---
    b = Counter()
    surv = db.execute(
        "select b.cve_id,b.hash,b.fn_id,b.path "
        "from unsafe_block b join unsafe_block_fix f "
        "on b.cve_id=f.cve_id and b.hash=f.hash and b.fn_id=f.fn_id "
        "and b.path=f.path group by 1,2,3,4").fetchall()
    b["surv_rows"] = len(surv)
    cves = {r[0] for r in surv}
    for cve in cves:
        url = db.execute("select repo_url from commit_life_spans where cve_id=?",
                         (cve,)).fetchone()
        wt = repo_dir(url[0]) if url else None
        b["cve_total"] += 1
        if not wt:
            b["no_worktree"] += 1
            continue
        b["cve_with_worktree"] += 1
    print("A (RQ4 positives):", dict(a))
    print("B (surviving blocks):", dict(b))


if __name__ == "__main__":
    main()
