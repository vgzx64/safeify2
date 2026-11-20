"""Combine analyzer-based and diff-based transition candidates.

Outputs:
    out/manifest.jsonl          all unique candidates, unreviewed
    out/safe_audit.csv          safe/removed candidates for manual review
    out/unsafe_audit.csv        unsafe-to-unsafe candidates for manual review
    out/manifest_stats.json
"""

from __future__ import annotations

import csv
import json
import re
import sqlite3
from collections import Counter
from pathlib import Path

DB = Path("/mnt/tc2015_p5/Code/rust_ecosystem/CVEfixes.db")
OUT = Path(__file__).resolve().parent / "out"


def norm(s: str) -> str:
    return "\n".join(" ".join(x.split()) for x in s.splitlines() if x.strip())


def code_only(s: str) -> str:
    return "\n".join(re.sub(r"//.*$", "", line) for line in s.splitlines())


def auto_category(r: dict) -> str:
    old = code_only(r.get("old_snippet", ""))
    new = code_only(r.get("safe_snippet", ""))
    if re.search(r"\bunsafe\s+(?:fn|impl|trait)\b", old) or re.search(
        r"\bunsafe\s+(?:fn|impl|trait)\b", new
    ):
        return "signature"
    if re.search(
        r"\b(assert!|assert_eq!|checked_|saturating_|resize|truncate|zeroed|MaybeUninit|catch_unwind|min\()",
        new,
    ):
        return "guard_or_init"
    api = r.get("api_guess") or ""
    if api and api in new:
        return "same_api_refactor"
    return "other"


def load_cves():
    con = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
    con.row_factory = sqlite3.Row
    meta = {}
    for r in con.execute("select id, package, severity, summary from cve"):
        meta[str(r["id"])] = {
            "package": r["package"],
            "severity": r["severity"],
            "summary": r["summary"],
        }
    cats = {}
    for r in con.execute("select cve_id, sfp_category from cve_sfp"):
        cats.setdefault(str(r["cve_id"]), []).append(r["sfp_category"])
    con.close()
    for k, v in meta.items():
        v["sfp_categories"] = sorted(set(cats.get(k, [])))
    return meta


def load_labels():
    p = Path(__file__).resolve().parent / "labels_safe.csv"
    if not p.exists():
        return {}
    with p.open(newline="") as f:
        return {r["id"]: r for r in csv.DictReader(f)}


def main() -> int:
    cves = load_cves()
    labels = load_labels()
    analyzer = [json.loads(x) for x in (OUT / "candidates.jsonl").open()]
    diff = [json.loads(x) for x in (OUT / "diff_candidates.jsonl").open()]
    pat_path = OUT / "pattern_candidates.jsonl"
    pattern = [json.loads(x) for x in pat_path.open()] if pat_path.exists() else []

    rows = []
    for r in analyzer:
        rr = dict(r)
        rr["source_method"] = "analyzer"
        rr["observed"] = {
            "replaced_safe": "safe",
            "removed": "removed",
            "replaced_unsafe": "unsafe",
        }[r["candidate_type"]]
        rows.append(rr)
    for r in diff:
        rr = dict(r)
        rr["source_method"] = "diff"
        rr["observed"] = {
            "diff_safe": "safe",
            "diff_removed": "removed",
            "diff_unsafe": "unsafe",
        }[r["candidate_type"]]
        rows.append(rr)
    base_safe_fns = {
        (r["commit"], r["path"], r.get("fn_id", ""))
        for r in rows
        if r["observed"] in ("safe", "conditional")
    }
    for r in pattern:
        key = (r["commit"], r["path"], r.get("fn_id", ""))
        if key in base_safe_fns:
            continue
        rr = dict(r)
        rr["source_method"] = "pattern"
        rows.append(rr)

    # Deduplicate on the actual old text. Prefer a reviewed row, then the
    # analyzer row (function id/block span), then the targeted pattern row.
    priority = {
        "labeled": 4,
        "analyzer": 3,
        "pattern": 2,
        "diff": 1,
    }
    seen = {}
    for r in rows:
        k = (r["commit"], r["path"], norm(r["old_snippet"]))
        rank = "labeled" if r["id"] in labels else r["source_method"]
        if k not in seen:
            seen[k] = (r, rank)
            continue
        prev, prev_rank = seen[k]
        if priority[rank] > priority[prev_rank]:
            seen[k] = (r, rank)
    rows = [r for r, _ in seen.values()]
    uniq = rows

    for r in uniq:
        meta = cves.get(str(r["cve_id"]), {})
        r.setdefault("parent_commit", "")
        r.setdefault("fn_id", "")
        r["package"] = meta.get("package")
        r["severity"] = meta.get("severity")
        r["summary"] = meta.get("summary")
        r["sfp_categories"] = meta.get("sfp_categories", [])
        if r["observed"] == "unsafe":
            r["auto_category"] = auto_category(r)
        lab = labels.get(r["id"])
        if lab:
            r["review_status"] = "reviewed"
            r["label"] = lab["label"]
            r["mechanism"] = lab["mechanism"]
            r["notes"] = lab["notes"]
            if lab["label"] == "conditional" and r["observed"] == "safe":
                r["observed"] = "conditional"
        else:
            r["review_status"] = "unreviewed"
            r["label"] = "unreviewed"
            r["notes"] = ""

    with (OUT / "manifest.jsonl").open("w") as f:
        for r in uniq:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")

    for observed, name in (
        ("safe", "safe_audit.csv"),
        ("conditional", "conditional_audit.csv"),
        ("unsafe", "unsafe_audit.csv"),
    ):
        subset = [r for r in uniq if r["observed"] == observed]
        with (OUT / name).open("w", newline="") as f:
            w = csv.writer(f)
            w.writerow([
                "id", "method", "observed", "repo", "cve", "package", "severity",
                "sfp_categories", "commit", "parent_commit", "path", "fn", "api",
                "span_start", "span_end", "old_snippet", "safe_snippet",
                "auto_category", "label", "notes",
            ])
            for r in sorted(subset, key=lambda x: (x["repo_name"], x["path"], x["span_start"])):
                w.writerow([
                    r["id"], r["source_method"], r["observed"], r["repo_name"],
                    r["cve_id"], r.get("package"), r.get("severity"),
                    ";".join(r.get("sfp_categories") or []), r["commit"],
                    r.get("parent_commit"), r["path"], r.get("fn_id"),
                    r.get("api_guess"), r["span_start"], r["span_end"],
                    r["old_snippet"], r["safe_snippet"],
                    r.get("auto_category", ""), r.get("label", ""), r.get("notes", ""),
                ])

    stats = {
        "total_unique": len(uniq),
        "by_observed": dict(Counter(r["observed"] for r in uniq)),
        "by_method": dict(Counter(r["source_method"] for r in uniq)),
        "by_repo": dict(Counter(r["repo_name"] for r in uniq).most_common()),
        "by_cve": dict(Counter(r["cve_id"] for r in uniq).most_common()),
        "by_api": dict(Counter(r.get("api_guess") or "unknown" for r in uniq).most_common()),
        "safe_repos": len(set(r["repo_name"] for r in uniq if r["observed"] == "safe")),
        "safe_cves": len(set(r["cve_id"] for r in uniq if r["observed"] == "safe")),
        "conditional_repos": len(set(r["repo_name"] for r in uniq if r["observed"] == "conditional")),
        "conditional_cves": len(set(r["cve_id"] for r in uniq if r["observed"] == "conditional")),
        "unsafe_repos": len(set(r["repo_name"] for r in uniq if r["observed"] == "unsafe")),
        "unsafe_cves": len(set(r["cve_id"] for r in uniq if r["observed"] == "unsafe")),
        "unsafe_categories": dict(Counter(r.get("auto_category") for r in uniq if r["observed"] == "unsafe")),
    }
    (OUT / "manifest_stats.json").write_text(json.dumps(stats, indent=2) + "\n")
    print(json.dumps(stats, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
