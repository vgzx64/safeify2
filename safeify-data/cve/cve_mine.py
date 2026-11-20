"""Mine unsafe->safe (positive) and unsafe->unsafe (negative) transitions.

Reads CVEfixes.db READ-ONLY. Writes JSON report to /tmp only (no repo writes).

Positives: 114 verified RQ4 rows (converted_to_safe=1, verified=1) + the 22
  unsafe-reducing commits from vul_safe_unsafe.
Negatives: unsafe_block rows present in BOTH unsafe_block and unsafe_block_fix
  (same cve_id/hash/fn_id/path) from the 276 same-count commits = unsafe that
  survived the fix -> irreplaceable/encapsulateable (gold N/M analogue).

Per-file classification on file_change diffs: net unsafe removed / added,
sinks (detect-API regex) removed / added / kept.
"""
from __future__ import annotations

import json
import re
import sqlite3
from collections import Counter
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
ECOSYSTEM = REPO / "rust_ecosystem"
DB = str(ECOSYSTEM / "CVEfixes.db")
OUT = "/tmp/cve_mine_report.json"
RQ4_MANIFEST = str(ECOSYSTEM / "rq4_block_conversion_manifest.csv")

SINK_RX = re.compile(
    r"\b(get_unchecked|get_unchecked_mut|unwrap_unchecked|unchecked_add|"
    r"unchecked_mul|transmute|transmute_copy|zeroed|uninitialized|"
    r"assume_init|from_raw|from_ptr|from_raw_parts|set_len|offset_from|"
    r"as_ref|as_mut|read_volatile|write_volatile|drop_in_place|dangling|"
    r"read|write|copy|copy_nonoverlapping|write_bytes)\b")
UNSAFE_RX = re.compile(r"\bunsafe\b")


def classify_diff(diff: str | None) -> dict:
    minus_unsafe = plus_unsafe = 0
    minus_sinks: set[str] = set()
    plus_sinks: set[str] = set()
    n_hunks = 0
    for line in (diff or "").splitlines():
        if line.startswith("@@"):
            n_hunks += 1
            continue
        if line.startswith("---") or line.startswith("+++"):
            continue
        if line.startswith("-"):
            body = line[1:]
            if UNSAFE_RX.search(body):
                minus_unsafe += 1
            minus_sinks.update(SINK_RX.findall(body))
        elif line.startswith("+"):
            body = line[1:]
            if UNSAFE_RX.search(body):
                plus_unsafe += 1
            plus_sinks.update(SINK_RX.findall(body))
    return {
        "hunks": n_hunks,
        "minus_unsafe": minus_unsafe,
        "plus_unsafe": plus_unsafe,
        "sinks_removed": sorted(minus_sinks - plus_sinks),
        "sinks_added": sorted(plus_sinks - minus_sinks),
        "sinks_kept": sorted(minus_sinks & plus_sinks),
    }


def main() -> None:
    db = sqlite3.connect("file:%s?mode=ro" % DB, uri=True)
    # commit strata from vul_safe_unsafe
    rows = db.execute(
        "select cve_id,hash,unsafe_func,unsafe_block,"
        "unsafe_func_fix,unsafe_block_fix from vul_safe_unsafe").fetchall()
    reducing, same, adding = [], [], []
    for r in rows:
        a = int(r[2] or 0) + int(r[3] or 0)
        b = int(r[4] or 0) + int(r[5] or 0)
        (reducing if a > b else same if a == b else adding).append(r)
    print(f"commits: total={len(rows)} reducing={len(reducing)} "
          f"same={len(same)} adding={len(adding)}", flush=True)
    red_hashes = {r[1] for r in reducing}
    same_hashes = {r[1] for r in same}

    # RQ4 verified positives
    import csv
    rq4 = [r for r in csv.DictReader(open(RQ4_MANIFEST, encoding="utf-8"))
           if r.get("converted_to_safe") == "1"
           and r.get("verified_conversion") == "1"]
    print(f"RQ4 verified positives: {len(rq4)}", flush=True)

    # per-file diff classification (bounded: only .rs MODIFY in strata)
    files: list[dict] = []
    fc = db.execute(
        "select hash,old_path,new_path,change_type,diff from file_change"
    ).fetchall()
    print(f"file_change rows: {len(fc)}", flush=True)
    for (h, o, n, t, d) in fc:
        if h not in red_hashes and h not in same_hashes:
            continue
        p = n or o or ""
        if not p.endswith(".rs"):
            continue
        if not UNSAFE_RX.search(d or ""):
            continue
        c = classify_diff(d or "")
        stratum = ("reducing" if h in red_hashes
                   else "same /* unsafe survived */")
        files.append({"hash": h, "path": p, "change_type": t,
                      "stratum": stratum, "diff_len": len(d or ""), **c})

    # negatives: surviving blocks (same key in both tables) in same-commits
    surv = db.execute(
        "select b.cve_id,b.hash,b.fn_id,b.path "
        "from unsafe_block b join unsafe_block_fix f "
        "on b.cve_id=f.cve_id and b.hash=f.hash "
        "and b.fn_id=f.fn_id and b.path=f.path").fetchall()
    surv_same = [s for s in surv if s[1] in same_hashes]
    print(f"surviving blocks total={len(surv)} in-same-commits={len(surv_same)}",
          flush=True)

    tr = [f for f in files if f["minus_unsafe"] > f["plus_unsafe"]]
    te = [f for f in files if f["plus_unsafe"] > f["minus_unsafe"]]
    sg = [f for f in files if f["sinks_removed"]]
    hist = Counter()
    for f in files:
        hist.update(f["sinks_removed"])
    report = {
        "strata": {"reducing": len(reducing), "same": len(same),
                   "adding": len(adding)},
        "rq4_verified_positives": len(rq4),
        "surviving_blocks_same_commits": len(surv_same),
        "summary": {"unsafe_rs_diffs": len(files),
                    "net_unsafe_removed": len(tr),
                    "net_unsafe_added": len(te),
                    "with_sink_removed": len(sg)},
        "sinks_removed_hist": dict(hist.most_common()),
        "files": files,
    }
    json.dump(report, open(OUT, "w"), indent=1)
    print(f"unsafe .rs diffs: {len(files)} | net-removed: {len(tr)} | "
          f"net-added: {len(te)} | sink-removed: {len(sg)}")
    print("sinks removed hist:", dict(hist.most_common(20)))
    print("wrote", OUT)


if __name__ == "__main__":
    main()
