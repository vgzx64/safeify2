"""Probe exact line-span semantics for the RQ4 manifest and unsafe_block tables.

Questions:
  Q1  RQ4 span_start/span_end -- line numbers in the PRE-fix file?  do they
      delimit an `unsafe {` block?
  Q2  unsafe_block.span_* -- same question.
  Q3  unsafe_block_fix.span_* -- line numbers in the POST-fix file?
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


def main():
    db = sqlite3.connect("file:%s?mode=ro" % DB, uri=True)
    rq4 = [r for r in csv.DictReader(open(RQ4, encoding="utf-8"))
           if r.get("converted_to_safe") == "1"
           and r.get("verified_conversion") == "1"]

    q = Counter()
    for r in rq4[:25]:
        h, path = r["hash"], r["path"]
        wt = repo_dir(r["repo_url"])
        if not wt:
            q["no_wt"] += 1
            continue
        par = db.execute("select parents from ext_commits where hash=?",
                         (h,)).fetchone()
        if not par or not par[0]:
            q["no_par"] += 1
            continue
        pre = show(wt, par[0].split()[0], path)
        post = show(wt, h, path)
        if not pre or not post:
            q["no_file"] += 1
            continue
        pl, pol = pre.splitlines(), post.splitlines()
        s, e = r["span_start"], r["span_end"]
        seg_pre = seg(pl, s, e)
        seg_post_same = seg(pol, s, e)
        q["checked"] += 1
        if "unsafe" in seg_pre:
            q["pre_span_has_unsafe"] += 1
        if seg_pre.strip().startswith("unsafe"):
            q["pre_span_starts_unsafe"] += 1
        if "unsafe" in seg_post_same:
            q["post_samelines_has_unsafe"] += 1
        else:
            q["post_samelines_clean"] += 1
        if q["checked"] <= 4:
            print("=" * 70)
            print("cve", r["cve_id"], "fn", r["fn_id"], "span", s, e)
            print("  PRE  span :", repr(seg_pre[:300]))
            print("  POST span :", repr(seg_post_same[:300]))
    print("Q1 RQ4 spans:", dict(q))

    # Q2/Q3 unsafe_block tables
    q2 = Counter()
    rows = db.execute(
        "select b.cve_id,b.hash,b.fn_id,b.path,b.span_start,b.span_end,"
        "f.span_start,f.span_end "
        "from unsafe_block b join unsafe_block_fix f "
        "on b.cve_id=f.cve_id and b.hash=f.hash and b.fn_id=f.fn_id "
        "and b.path=f.path limit 40").fetchall()
    for cve, h, fn_id, path, s, e, fs, fe in rows:
        url = db.execute("select repo_url from commit_life_spans where cve_id=?",
                         (cve,)).fetchone()
        wt = repo_dir(url[0]) if url else None
        if not wt:
            q2["no_wt"] += 1
            continue
        par = db.execute("select parents from ext_commits where hash=?",
                         (h,)).fetchone()
        if not par or not par[0]:
            q2["no_par"] += 1
            continue
        pre = show(wt, par[0].split()[0], path)
        post = show(wt, h, path)
        if not pre or not post:
            q2["no_file"] += 1
            continue
        pl, pol = pre.splitlines(), post.splitlines()
        a = seg(pl, s, e)
        b = seg(pol, fs, fe)
        q2["checked"] += 1
        if "unsafe" in a:
            q2["pre_has_unsafe"] += 1
        if a.strip().startswith("unsafe"):
            q2["pre_starts_unsafe"] += 1
        if "unsafe" in b:
            q2["post_has_unsafe"] += 1
    print("Q2/Q3 unsafe_block spans:", dict(q2))


if __name__ == "__main__":
    main()
