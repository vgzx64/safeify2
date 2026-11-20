"""Diagnose why 69 RQ4 rows fail to join `function`/`function_fix`.

Prints, per failing row: the fn_id, the function names present for that
(cve,hash,path), and whether a loose suffix match exists.
"""
import csv
import sqlite3

DB = "/home/dev2/Code/safeify2/research/rust_ecosystem/CVEfixes.db"
RQ4 = ("/home/dev2/Code/safeify2/research/rust_ecosystem/"
       "rq4_block_conversion_manifest.csv")


def main():
    db = sqlite3.connect("file:%s?mode=ro" % DB, uri=True)
    rows = [r for r in csv.DictReader(open(RQ4, encoding="utf-8"))
            if r.get("converted_to_safe") == "1"
            and r.get("verified_conversion") == "1"]
    shown = 0
    for r in rows:
        cve, h, path = r["cve_id"], r["hash"], r["path"]
        short = r["fn_id"].split("::")[-1]
        pre = db.execute(
            "select name,span_start,span_end from function where cve_id=? "
            "and hash=? and path=?", (cve, h, path)).fetchall()
        post = db.execute(
            "select name,span_start,span_end from function_fix where cve_id=? "
            "and hash=? and path=?", (cve, h, path)).fetchall()
        exact_pre = any(x[0] == short for x in pre)
        exact_post = any(x[0] == short for x in post)
        if exact_pre and exact_post:
            continue
        if shown >= 12:
            continue
        shown += 1
        print("CVE", cve, "fn_id", repr(r["fn_id"]), "path", path)
        print("   function names     :", [x[0] for x in pre][:12])
        print("   function_fix names :", [x[0] for x in post][:12])
        print("   exact pre/post:", exact_pre, exact_post)
    print("total rq4 rows:", len(rows))


if __name__ == "__main__":
    main()
