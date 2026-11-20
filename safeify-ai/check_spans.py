"""Check RQ4 span semantics: are span_start/span_end indices into the
PRE-fix (parent commit) file, the POST-fix file, or neither?

Writes a verdict per row to stdout.
"""
import csv
import os
import re
import sqlite3
import subprocess

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


def main():
    db = sqlite3.connect("file:%s?mode=ro" % DB, uri=True)
    rows = [r for r in csv.DictReader(open(RQ4, encoding="utf-8"))
            if r.get("converted_to_safe") == "1"
            and r.get("verified_conversion") == "1"]
    stats = {"pre_unsafe": 0, "post_unsafe": 0, "pre_only": 0, "post_only": 0,
             "neither": 0, "no_file": 0, "checked": 0}
    samples = []
    for r in rows[:40]:
        wt = repo_dir(r["repo_url"])
        if not wt:
            stats["no_file"] += 1
            continue
        h = r["hash"]
        par = db.execute("select parents from ext_commits where hash=?",
                         (h,)).fetchone()
        if not par or not par[0]:
            stats["no_file"] += 1
            continue
        parent = par[0].split()[0]
        pre = show(wt, parent, r["path"])
        post = show(wt, h, r["path"])
        if not pre or not post:
            stats["no_file"] += 1
            continue
        s, e = int(r["span_start"]), int(r["span_end"])
        plines, polines = pre.splitlines(), post.splitlines()
        pre_seg = "\n".join(plines[s - 1:e]) if s <= len(plines) else ""
        post_seg = "\n".join(polines[s - 1:e]) if s <= len(polines) else ""
        has_u = lambda t: "unsafe" in t
        stats["checked"] += 1
        if has_u(pre_seg) and not has_u(post_seg):
            stats["pre_only"] += 1
        elif has_u(post_seg) and not has_u(pre_seg):
            stats["post_only"] += 1
        elif has_u(pre_seg) and has_u(post_seg):
            stats["pre_unsafe"] += 1
        else:
            stats["neither"] += 1
        if len(samples) < 6:
            samples.append((r["cve_id"], r["fn_id"], s, e,
                            pre_seg[:200], post_seg[:200]))
    for sm in samples:
        print("CVE", sm[0], sm[1], "span", sm[2], sm[3])
        print("  PRE :", repr(sm[4]))
        print("  POST:", repr(sm[5]))
    print(stats)


if __name__ == "__main__":
    main()
