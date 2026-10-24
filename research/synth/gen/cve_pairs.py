"""CVE rows -> pair-format CSVs through the SAME extract_ast + preprocess pipeline.

Reads: /tmp/cve_pairs.jsonl (from detect/cve_extract.py).
Writes (research/synth/out/):
  cve_pairs.csv       ,text1,text2,label  (unsafe->safe transition pairs:
                      text1=vuln-side seq, text2=fixed-side seq, label=1;
                      unsafe->unsafe rows pair against themselves label=-1
                      as hard negatives)
  cve_manifest.jsonl  provenance per row (audit schema + verification +
                      seq_sha256 + cve_split assignment)
  cve_split.json      {cve_train: [...repos...], cve_holdout: [...repos...]}

Split rule: by REPO (no repo in both). Repos sorted, every 10th repo (by
sha256) -> holdout (~30% of rows target). Frozen SafeNet splits untouched;
leakage quarantine: CVE seq_sha256 colliding with any frozen-split sequence
is flagged and excluded from cve_pairs.csv (kept in manifest, quarantined).
"""
from __future__ import annotations

import csv
import hashlib
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                "..", "synth", "pipe"))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                "..", "synth", "gen"))
import preprocess  # noqa: E402
import syn_parser  # noqa: E402

IN_JSONL = "/tmp/cve_pairs.jsonl"
SYNTH_ROOT = "/home/dev2/Code/safeify2/research/synth"
OUT_CSV = os.path.join(SYNTH_ROOT, "out", "cve_pairs.csv")
OUT_MANIFEST = os.path.join(SYNTH_ROOT, "out", "cve_manifest.jsonl")
OUT_SPLIT = os.path.join(SYNTH_ROOT, "out", "cve_split.json")


def seq_of(code: str | None) -> tuple[str | None, str | None]:
    """Rust text -> preorder seq (or (None, err))."""
    if not code:
        return None, "empty"
    try:
        dump = syn_parser.parse_to_debug(code)
    except Exception as e:  # syn parse failure
        return None, f"syn: {e}"[:200]
    try:
        seq = preprocess.debug_to_preorder(dump)
        return (seq if seq.split() else None), None
    except AttributeError:
        return None, "no debug_to_preorder"


def frozen_seqs() -> set[str]:
    seqs: set[str] = set()
    for corpus in ("gh", "kb"):
        root = os.path.join(SYNTH_ROOT, "out", "ast_json_real", corpus)
        for dp, _, files in os.walk(root):
            for f in files:
                if not f.endswith(".json"):
                    continue
                try:
                    seqs.add(json.load(open(os.path.join(dp, f))))
                except Exception:
                    pass
    return seqs


def main() -> None:
    rows = [json.loads(l) for l in open(IN_JSONL, encoding="utf-8")
            if l.strip()]
    print(f"cve rows in: {len(rows)}", flush=True)
    frozen = frozen_seqs()
    print(f"frozen sequences loaded: {len(frozen)}", flush=True)

    repos = sorted({r.get("repo_url", "") for r in rows if r.get("repo_url")})
    holdout_repos = {u for u in repos
                     if int(hashlib.sha256(u.encode()).hexdigest(), 16)
                     % 10 in (0, 1, 2)}
    print(f"repos: {len(repos)} holdout: {len(holdout_repos)}", flush=True)

    pairs: list[tuple[str, str, int]] = []
    manifest = []
    stats = {"ok_pos": 0, "ok_neg": 0, "parse_fail": 0, "quarantined": 0,
             "no_fixed": 0}
    for i, r in enumerate(rows):
        repo = r.get("repo_url", "")
        split = ("cve_holdout" if repo in holdout_repos else "cve_train")
        s1, e1 = seq_of(r.get("unsafe_code"))
        s2, e2 = seq_of(r.get("safe_code"))
        rec = {"id": f"cve-{i}", "cve_id": r.get("cve_id"),
               "hash": r.get("hash"), "repo_url": repo, "path": r.get("path"),
               "fn_id": r.get("fn_id"), "span": r.get("span"),
               "sfp_category": r.get("sfp_category"),
               "outcome": r.get("outcome"), "source": r.get("source"),
               "verification": {"syn_parse_unsafe": e1 is None,
                                "syn_parse_safe": e2 is None,
                                "parse_error": e1 or e2},
               "cve_split": split, "seq_sha256": None, "quarantined": False,
               "ok": False}
        if r.get("outcome") == "unsafe_to_safe" and s1 and s2:
            sha = hashlib.sha256(s1.encode()).hexdigest()
            rec["seq_sha256"] = sha
            if s1 in frozen or s2 in frozen:
                rec["quarantined"] = True
                stats["quarantined"] += 1
            else:
                rec["ok"] = True
                pairs.append((s1, s2, 1))
                stats["ok_pos"] += 1
        elif r.get("outcome") == "unsafe_to_unsafe" and s1:
            sha = hashlib.sha256(s1.encode()).hexdigest()
            rec["seq_sha256"] = sha
            if s1 in frozen:
                rec["quarantined"] = True
                stats["quarantined"] += 1
            else:
                rec["ok"] = True
                pairs.append((s1, s1, -1))  # self-pair hard negative
                stats["ok_neg"] += 1
        else:
            if e1 or (r.get("outcome") == "unsafe_to_safe" and e2):
                stats["parse_fail"] += 1
            else:
                stats["no_fixed"] += 1
        manifest.append(rec)

    with open(OUT_CSV, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["", "text1", "text2", "label"])
        for j, (a, b, lab) in enumerate(pairs):
            w.writerow([j, a, b, lab])
    with open(OUT_MANIFEST, "w", encoding="utf-8") as f:
        for rec in manifest:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    json.dump({"holdout_repos": sorted(holdout_repos),
               "train_repos": sorted(set(repos) - holdout_repos)},
              open(OUT_SPLIT, "w"), indent=1)
    print(stats)
    print(f"pairs: {len(pairs)} -> {OUT_CSV}")
    print(f"manifest: {len(manifest)} -> {OUT_MANIFEST}")


if __name__ == "__main__":
    main()
