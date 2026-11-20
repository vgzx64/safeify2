#!/usr/bin/env python3
"""Validate real-CVE pairs produced by safeify-data/cve/cve_pairs.py.

Checks: label/field sanity, span validity, block-level survival evidence,
sink coverage, duplicate structure, and cross-corpus leakage against the
synthetic corpus and SafeNet.
"""
import json
import os
import re
import sys
from collections import Counter, defaultdict

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "detect", "out")
JSONL = os.path.join(OUT, "cve_pairs.jsonl")
REPORT = os.path.join(OUT, "cve_pairs_report.json")


def norm(code):
    """Same normalization as cve_pairs.py (kept in sync manually)."""
    if not code:
        return ""
    code = re.sub(r"//[^\n]*", "", code)
    code = re.sub(r"/\*.*?\*/", "", code, flags=re.S)
    code = re.sub(r"\s+", " ", code)
    return code.strip()


def load():
    return [json.loads(l) for l in open(JSONL)]


def main():
    recs = load()
    issues = []
    warn = []

    ids = [r["id"] for r in recs]
    if len(set(ids)) != len(ids):
        issues.append("duplicate ids")
    for r in recs:
        if r.get("label") not in ("Y", "N"):
            issues.append(f"{r['id']}: bad label {r.get('label')!r}")
        if not r.get("unsafe_code"):
            issues.append(f"{r['id']}: empty unsafe_code")
        if not r.get("safe_code"):
            issues.append(f"{r['id']}: empty safe_code")
        if "unsafe {" not in (r.get("unsafe_code") or ""):
            issues.append(f"{r['id']}: unsafe_code has no 'unsafe {{'")
        if r.get("unit") != "function":
            warn.append(f"{r['id']}: unit={r.get('unit')}")

    for r in recs:
        if r["label"] == "N" and not r.get("block_survived"):
            issues.append(f"{r['id']}: N without verified survival")
        if r["label"] == "Y" and r.get("block_disappeared") is False:
            warn.append(f"{r['id']}: Y but unsafe block text still present")

    dups = [r for r in recs if r.get("duplicate_of")]
    idset = set(ids)
    for r in dups:
        if r["duplicate_of"] not in idset:
            issues.append(f"{r['id']}: duplicate_of unknown id {r['duplicate_of']}")

    # same normalized unsafe code must not carry conflicting labels
    lab = {r["id"]: r["label"] for r in recs}
    by_norm = defaultdict(list)
    for r in recs:
        by_norm[norm(r.get("unsafe_code"))].append(r["id"])
    cross = [v for k, v in by_norm.items()
             if k and len({lab[i] for i in v}) > 1]
    if cross:
        issues.append(f"{len(cross)} normalized-unsafe groups with "
                      f"conflicting labels")

    # ---------------- leakage: vs synthetic corpus ----------------
    synth_files = [
        os.path.join(ROOT, "synth", "out", "pairs_manifest.jsonl"),
        os.path.join(ROOT, "synth", "out", "gen_records_inject.jsonl"),
        os.path.join(ROOT, "synth", "out", "gen_records_template.jsonl"),
    ]
    syn_norm = set()
    for f in synth_files:
        if not os.path.exists(f):
            continue
        for line in open(f):
            try:
                d = json.loads(line)
            except Exception:
                continue
            for k in ("unsafe_code", "code", "snippet", "source_code",
                      "before", "pre"):
                v = d.get(k)
                if isinstance(v, str) and v.strip():
                    syn_norm.add(norm(v))
    if syn_norm:
        hits = [r["id"] for r in recs
                if norm(r.get("unsafe_code")) in syn_norm
                or norm(r.get("unsafe_block_code")) in syn_norm]
        print(f"OK  synthetic corpus: {len(syn_norm)} snippets compared, "
              f"{len(hits)} exact normalized matches")
        if hits:
            warn.append(f"{len(hits)} records overlap the synthetic corpus "
                        f"(e.g. {hits[:5]})")

    # ---------------- leakage: vs SafeNet ----------------
    sn_norm = set()
    for d in ("/home/dev2/Code/safeify2/vendors/SafeNet",):
        if not os.path.isdir(d):
            continue
        for dirpath, _, files in os.walk(d):
            for fn in files:
                if fn.endswith(".rs"):
                    try:
                        sn_norm.add(norm(open(os.path.join(dirpath, fn),
                                              errors="ignore").read()))
                    except Exception:
                        pass
    if sn_norm:
        hits = [r["id"] for r in recs
                if norm(r.get("unsafe_code")) in sn_norm
                or norm(r.get("unsafe_block_code")) in sn_norm]
        print(f"OK  SafeNet: {len(sn_norm)} .rs files compared, "
              f"{len(hits)} exact normalized matches")
        if hits:
            warn.append(f"{len(hits)} records match SafeNet code exactly")

    # ---------------- report ----------------
    print()
    print(f"records            : {len(recs)}")
    print(f"labels             : {dict(Counter(r['label'] for r in recs))}")
    print(f"units              : {dict(Counter(r.get('unit') for r in recs))}")
    print(f"outcomes           : {dict(Counter(r.get('outcome') for r in recs))}")
    print(f"exact dup (unsafe) : {len(dups)}")
    print(f"unique repos       : {len({r.get('repo_url') for r in recs})}")
    print(f"unique CVEs        : {len({r.get('cve_id') for r in recs})}")
    print(f"unique commits     : {len({r.get('hash') for r in recs})}")
    for L in ("Y", "N"):
        s = [r for r in recs if r["label"] == L]
        ws = sum(1 for r in s if r.get("unsafe_sinks"))
        print(f"  {L}: n={len(s):4d}  with_sink={ws:4d}  "
              f"no_sink={len(s)-ws:4d}  "
              f"unique_norm={len({norm(r.get('unsafe_code')) for r in s})}")
    print()
    if issues:
        print(f"ISSUES ({len(issues)}):")
        for i in issues[:40]:
            print("  !", i)
    else:
        print("ISSUES: none")
    if warn:
        print(f"WARNINGS ({len(warn)}):")
        for w in warn[:40]:
            print("  ~", w)
    else:
        print("WARNINGS: none")
    return 1 if issues else 0


if __name__ == "__main__":
    sys.exit(main())
