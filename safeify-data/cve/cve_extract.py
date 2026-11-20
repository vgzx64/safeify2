"""Extract CVE validation snippets: unsafe->safe positives + unsafe->unsafe negatives.

Reads: CVEfixes.db (ro), rq4_block_conversion_manifest.csv, repos_worktree/.
Writes: /tmp/cve_pairs.jsonl (audit-ready provenance) + /tmp/cve_extract_report.json.

Positive: RQ4 verified rows: vulnerable fn via `git show <hash>^:<path>`,
  fixed via `git show <hash>:<path>`. Requires detect-API sink on vuln side.
Negative: surviving unsafe_block rows (same key both tables): block text
  from worktree at <hash>. Label N/M later by verdict policy.

Degrades gracefully: missing worktree/rev -> cve_diff_fallback. Never crashes.
"""
from __future__ import annotations

import csv
import json
import os
import re
import sqlite3
import subprocess
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
ECOSYSTEM = REPO / "rust_ecosystem"
DB = str(ECOSYSTEM / "CVEfixes.db")
RQ4 = str(ECOSYSTEM / "rq4_block_conversion_manifest.csv")
WT = str(ECOSYSTEM / "repos_mirror")
OUT_JSONL = "/tmp/cve_pairs.jsonl"
OUT_REPORT = "/tmp/cve_extract_report.json"

SINK_RX = re.compile(
    r"\b(get_unchecked|get_unchecked_mut|unwrap_unchecked|unchecked_add|"
    r"unchecked_mul|transmute|transmute_copy|zeroed|uninitialized|"
    r"assume_init|from_raw|from_ptr|from_raw_parts|set_len|offset_from|"
    r"as_ref|as_mut|read_volatile|write_volatile|drop_in_place|dangling|"
    r"ptr\s*::\s*(read|write|copy|copy_nonoverlapping|write_bytes))\b")


def repo_dir(repo_url: str) -> str | None:
    m = re.search(r"github\.com/([^/]+/[^/]+?)(\.git)?/?$", repo_url or "")
    if not m:
        return None
    d = os.path.join(WT, m.group(1).replace("/", "_"))
    return d if os.path.isdir(d) else None


def git_show(wt: str, rev: str, path: str) -> str | None:
    try:
        r = subprocess.run(["git", "-C", wt, "show", f"{rev}:{path}"],
                           capture_output=True, text=True, timeout=60)
    except Exception:
        return None
    return r.stdout if r.returncode == 0 else None


def fn_text(src: str, fn_id: str) -> str | None:
    short = (fn_id or "").split("::")[-1]
    if not short or not src:
        return None
    lines = src.splitlines()
    idx = next((i for i, l in enumerate(lines)
                if re.search(r"\bfn\s+" + re.escape(short) + r"\b", l)), None)
    if idx is None:
        idx = next((i for i, l in enumerate(lines) if short in l), None)
    if idx is None:
        return None
    lo = max(0, idx - 5)
    depth = 0
    hi = idx + 1
    started = False
    for i in range(idx, min(len(lines), idx + 400)):
        depth += lines[i].count("{") - lines[i].count("}")
        if "{" in lines[i]:
            started = True
        hi = i + 1
        if started and depth <= 0:
            break
    return "\n".join(lines[lo:hi])


def main() -> None:
    db = sqlite3.connect("file:%s?mode=ro" % DB, uri=True)
    life = {str(r[0]): (r[1], r[2])
            for r in db.execute("select cve_id,hash,repo_url "
                               "from commit_life_spans").fetchall()}
    rq4 = [r for r in csv.DictReader(open(RQ4, encoding="utf-8"))
           if r.get("converted_to_safe") == "1"
           and r.get("verified_conversion") == "1"]
    out = open(OUT_JSONL, "w", encoding="utf-8")
    stats = {"pos_ok": 0, "pos_nosink": 0, "pos_fallback": 0,
             "pos_missing": 0, "neg_ok": 0, "neg_missing": 0}

    for r in rq4:
        cve, h = r["cve_id"], r["hash"]
        repo_url = (life.get(cve) or (None, None))[1] or r.get("repo_url", "")
        wt = repo_dir(repo_url or "")
        rec: dict = {"cve_id": cve, "hash": h, "repo_url": repo_url,
                     "path": r["path"], "fn_id": r["fn_id"],
                     "span": [r["span_start"], r["span_end"]],
                     "sfp_category": r.get("sfp_category", ""),
                     "outcome": "unsafe_to_safe", "source": None,
                     "unsafe_code": None, "safe_code": None}
        old = new = None
        if wt:
            old = git_show(wt, h + "^", r["path"])
            new = git_show(wt, h, r["path"])
        if old and new:
            rec["source"] = "cve_worktree"
            rec["unsafe_code"] = fn_text(old, r["fn_id"]) or old[:6000]
            rec["safe_code"] = fn_text(new, r["fn_id"]) or new[:6000]
            if SINK_RX.search(rec["unsafe_code"] or ""):
                stats["pos_ok"] += 1
            else:
                stats["pos_nosink"] += 1
        else:
            d = db.execute("select diff from file_change where hash=? "
                           "and (new_path=? or old_path=?)",
                           (h, r["path"], r["path"])).fetchone()
            if d and d[0]:
                rec["source"] = "cve_diff_fallback"
                rec["unsafe_code"] = d[0][:6000]
                stats["pos_fallback"] += 1
            else:
                rec["source"] = "missing"
                stats["pos_missing"] += 1
        out.write(json.dumps(rec, ensure_ascii=False) + "\n")

    surv = db.execute(
        "select b.cve_id,b.hash,b.fn_id,b.path "
        "from unsafe_block b join unsafe_block_fix f "
        "on b.cve_id=f.cve_id and b.hash=f.hash "
        "and b.fn_id=f.fn_id and b.path=f.path "
        "group by b.cve_id,b.hash,b.fn_id,b.path "
        "limit 400").fetchall()
    seen = 0
    for (cve, h, fn_id, path) in surv:
        if seen >= 300:
            break
        repo_url = (life.get(str(cve)) or (None, None))[1] or ""
        wt = repo_dir(repo_url)
        if not wt:
            stats["neg_missing"] += 1
            continue
        src = git_show(wt, h, path)
        if not src:
            stats["neg_missing"] += 1
            continue
        block = fn_text(src, fn_id) or src[:6000]
        if "unsafe" not in (block or ""):
            continue
        rec = {"cve_id": str(cve), "hash": h, "repo_url": repo_url,
               "path": path, "fn_id": fn_id, "span": None,
               "sfp_category": "", "outcome": "unsafe_to_unsafe",
               "source": "cve_worktree", "unsafe_code": block,
               "safe_code": None}
        out.write(json.dumps(rec, ensure_ascii=False) + "\n")
        seen += 1
        stats["neg_ok"] += 1
    out.close()
    json.dump(stats, open(OUT_REPORT, "w"), indent=1)
    print(stats)
    print("wrote", OUT_JSONL, OUT_REPORT)


if __name__ == "__main__":
    main()
