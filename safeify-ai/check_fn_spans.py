"""Check `function` / `function_fix` span semantics.

Hypothesis: `function` rows hold PRE-fix (parent commit) function line spans,
`function_fix` rows hold POST-fix (fix commit) function line spans, keyed by
the same (cve_id, hash, path, name).

Prints, for a sample of CVEs, the extracted text from each side so the
hypothesis can be eyeballed.
"""
import os
import re
import sqlite3
import subprocess

DB = "/home/dev2/Code/safeify2/research/rust_ecosystem/CVEfixes.db"
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
    if s is None or e is None:
        return ""
    try:
        s, e = int(s), int(e)
    except (TypeError, ValueError):
        return ""
    if s > len(lines):
        return ""
    return "\n".join(lines[s - 1:e])


def main():
    db = sqlite3.connect("file:%s?mode=ro" % DB, uri=True)
    stats = {"pre_fn": 0, "post_fn": 0, "pre_only": 0, "post_only": 0,
             "neither": 0, "checked": 0}
    n = 0
    for cve, in db.execute("select distinct cve_id from function limit 12").fetchall():
        url = db.execute("select repo_url from commit_life_spans where cve_id=?",
                         (cve,)).fetchone()
        if not url:
            continue
        wt = repo_dir(url[0])
        if not wt:
            continue
        rows = db.execute("select hash,path,name,span_start,span_end "
                          "from function where cve_id=?", (cve,)).fetchall()
        fixes = {(h, p, nm): (s, e) for h, p, nm, s, e in db.execute(
            "select hash,path,name,span_start,span_end from function_fix "
            "where cve_id=?", (cve,)).fetchall()}
        for h, path, name, s, e in rows[:3]:
            par = db.execute("select parents from ext_commits where hash=?",
                             (h,)).fetchone()
            if not par or not par[0]:
                continue
            parent = par[0].split()[0]
            pre = show(wt, parent, path)
            post = show(wt, h, path)
            if not pre or not post:
                continue
            pl, pol = pre.splitlines(), post.splitlines()
            pseg = seg(pl, int(s), int(e))
            fs, fe = fixes.get((h, path, name), (None, None))
            qseg = seg(pol, fs, fe) if fs else ""
            stats["checked"] += 1
            if "fn" in pseg and pseg.strip().startswith(("fn", "pub fn", "async fn",
                                                         "pub async fn", "pub(crate) fn",
                                                         "pub(crate) async fn", "unsafe fn",
                                                         "pub unsafe fn", "pub(crate) unsafe fn")):
                stats["pre_fn"] += 1
            if qseg.strip().startswith(("fn", "pub fn", "async fn", "pub async fn",
                                        "pub(crate) fn", "pub(crate) async fn",
                                        "unsafe fn", "pub unsafe fn",
                                        "pub(crate) unsafe fn")):
                stats["post_fn"] += 1
            if n < 4:
                print("CVE", cve, name, "span", s, e, "| fix span", fs, fe)
                print("  PRE :", repr(pseg[:220]))
                print("  POST:", repr(qseg[:220]))
                n += 1
    print(stats)


if __name__ == "__main__":
    main()
