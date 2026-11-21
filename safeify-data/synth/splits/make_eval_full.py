"""Build the ENLARGED pair evaluation sets from the frozen split.

Companion to make_eval.py; run AFTER it (needs gallery.json and, like
make_eval.py, the per-machine AST cache out/ast_json_real/gh).

Why: the shipped <split>_pairs.csv files are within-API, query-query pairs
balanced by scarce positives — 76 pairs (38/38) for test, 10 (5/5) for valid,
3 both-N test pairs. At those sizes a macro-F1 difference of ~10 points is
inside noise and the safety FP rate is unmeasurable. This script materialises
a larger, stratified, still fully frozen evaluation from the SAME held-out
snippets plus the fixed KB gallery (which is training-side data by design —
the deployment task retrieves against it):

  POS-QG       query x gallery, same (api, pattern)     label +1
  POS-QQ       query x query (same split), same cell    label +1
  NEG-HARD-QG  query x gallery, same api, diff pattern  label -1
  NEG-HARD-QQ  query x query (same split), same api,
               diff pattern                             label -1
  NEG-XAPI-QG  query x gallery, different api, capped
               at --xapi-per-query per query (default 3) label -1

Label semantics are unchanged (1 iff same (api, pattern); converttrainset.py).
All hard negatives are kept (no downsampling); positives are ALL available
pairs. The set is therefore imbalanced (~17% positive for test) — report
macro-F1 / per-stratum metrics, not raw accuracy alone. The original
<split>_pairs.csv files are left byte-identical for backward compatibility.

Determinism: candidates are enumerated in sorted order, the only randomness
is random.Random(1234) for the xapi sample and the final shuffle — byte-
identical re-runs on an unchanged cache.

Usage: cd safeify-data/synth
        python splits/make_eval_full.py --split valid   # selection set
        python splits/make_eval_full.py --split test    # report-once set
        python splits/make_eval_full.py --split all
Then score with:
        python splits/eval_protocol.py --split test --pairs-preds P.csv --full
"""

import argparse
import json
import os
import random
import sys
from itertools import combinations

SPLITS_DIR = os.path.dirname(os.path.abspath(__file__))
SYNTH_ROOT = os.path.dirname(SPLITS_DIR)
SEED = 1234  # matches make_eval.py / gen/pairs.py convention

sys.path.insert(0, SPLITS_DIR)
from make_eval import (  # noqa: E402  (frozen-pipeline loaders: no drift)
    load_split_rows,
    load_verdicts,
    sha_file,
    write_pairs_csv,
)

XAPI_PER_QUERY_DEFAULT = 3
STRATA = ("POS-QG", "POS-QQ", "NEG-HARD-QG", "NEG-HARD-QQ", "NEG-XAPI-QG")


def load_gallery():
    """Fixed KB gallery from the committed gallery.json (frozen by make_eval)."""
    with open(os.path.join(SPLITS_DIR, "gallery.json"), encoding="utf-8") as f:
        gallery = json.load(f)["apis"]
    for api in gallery:
        gallery[api].sort(key=lambda g: (g["pattern_id"], g["id"]))
    return gallery


def build_pairs(rows, gallery, rng, xapi_per_query):
    """Enumerate the five strata; deterministic given rows, gallery, seed."""
    pairs = []  # each: dict(stratum, a, b, label) — a is always the query

    rows_sorted = sorted(rows, key=lambda r: r["rel_path"])
    by_api = {}
    for r in rows_sorted:
        by_api.setdefault(r["api"], []).append(r)

    # --- QG strata (query x fixed gallery) ---
    for q in rows_sorted:
        api, pat = q["api"], q["pattern_id"]
        same_api = gallery.get(api, [])
        pos_c, hard_c = [], []
        for g in same_api:
            rec = (q, g, g["pattern_id"] == pat)
            (pos_c if rec[2] else hard_c).append(rec)
        for q_, g, _ in pos_c:                      # POS-QG: all
            pairs.append({"stratum": "POS-QG", "a": q_, "b": g, "label": 1})
        for q_, g, _ in hard_c:                     # NEG-HARD-QG: all
            pairs.append({"stratum": "NEG-HARD-QG", "a": q_, "b": g, "label": -1})

    # --- QQ strata (within-API, query-query, same split) ---
    for api in sorted(by_api):
        for a, b in combinations(by_api[api], 2):
            same = a["pattern_id"] == b["pattern_id"]
            pairs.append({"stratum": "POS-QQ" if same else "NEG-HARD-QQ",
                          "a": a, "b": b, "label": 1 if same else -1})

    # --- NEG-XAPI-QG: capped random sample per query, sorted candidates ---
    for q in rows_sorted:
        cands = sorted(
            (g for other_api in sorted(gallery) if other_api != q["api"]
             for g in gallery[other_api]),
            key=lambda g: g["id"])
        for g in rng.sample(cands, min(xapi_per_query, len(cands))):
            pairs.append({"stratum": "NEG-XAPI-QG", "a": q, "b": g, "label": -1})

    rng.shuffle(pairs)
    return pairs


def build(split_name, verdicts, gallery, xapi_per_query):
    rows = load_split_rows(split_name, verdicts)
    if not rows:
        raise SystemExit(f"no rows in {split_name} split — run make_splits.py first")
    rng = random.Random(SEED)
    pairs = build_pairs(rows, gallery, rng, xapi_per_query)

    csv_path = os.path.join(SPLITS_DIR, f"{split_name}_pairs_full.csv")
    write_pairs_csv([(p["a"], p["b"], p["label"]) for p in pairs], csv_path)

    def pair_meta(i, p):
        a, b = p["a"], p["b"]
        return {
            "i": i,
            "stratum": p["stratum"],
            "api": a["api"],
            "p1": a["pattern_id"], "p2": b["pattern_id"],
            "v1": a["verdict"], "v2": b["verdict"],
            "label": p["label"],
            "q": a["rel_path"],
            "g": b["id"] if "id" in b else b["rel_path"],
            "g_kind": b.get("kind"),
            "same_text": a["text"] == b["text"],
        }

    by_stratum = {s: sum(1 for p in pairs if p["stratum"] == s) for s in STRATA}
    both_n_neg = sum(1 for p in pairs
                     if p["label"] == -1 and p["a"]["verdict"] == "N"
                     and p["b"]["verdict"] == "N")
    harmful_neg = sum(1 for p in pairs          # N query vs Y/M gallery, same api
                      if p["label"] == -1 and p["stratum"] == "NEG-HARD-QG"
                      and p["a"]["verdict"] == "N"
                      and p["b"].get("verdict") in ("Y", "M"))
    manifest = {
        "split": split_name,
        "seed": SEED,
        "construction": "enlarged stratified pairs; all hard negatives and "
                        "positives kept; xapi capped per query; see "
                        "splits/README.md (Full pair sets)",
        "xapi_per_query": xapi_per_query,
        "n_snippets": len(rows),
        "n_pairs": len(pairs),
        "by_stratum": by_stratum,
        "n_pos": sum(1 for p in pairs if p["label"] == 1),
        "n_neg": sum(1 for p in pairs if p["label"] == -1),
        "both_n_negatives": both_n_neg,
        "n_query_vs_ym_hard_negatives": harmful_neg,
        "same_text_pairs": sum(1 for p in pairs if p["a"]["text"] == p["b"]["text"]),
        "same_text_label_neg": sum(1 for p in pairs
                                   if p["label"] == -1
                                   and p["a"]["text"] == p["b"]["text"]),
        "gallery_entries": sum(len(v) for v in gallery.values()),
        "gallery_apis": len(gallery),
        "split_file_sha256": {s: sha_file(os.path.join(SPLITS_DIR, f"{s}.txt"))
                              for s in ("train", "valid", "test")},
        "gallery_sha256": sha_file(os.path.join(SPLITS_DIR, "gallery.json")),
        "pairs": [pair_meta(i, p) for i, p in enumerate(pairs)],
    }
    mf_path = os.path.join(SPLITS_DIR, f"{split_name}_eval_manifest_full.json")
    with open(mf_path, "w", encoding="utf-8") as f:
        json.dump(manifest, f, ensure_ascii=False)

    print(f"eval-full: {split_name} snippets={len(rows)} pairs={len(pairs)} "
          f"(pos={manifest['n_pos']} neg={manifest['n_neg']})")
    for s in STRATA:
        print(f"  {s}: {by_stratum[s]}")
    print(f"  both-N negatives: {both_n_neg}  "
          f"N-query x Y/M-gallery hard negatives: {harmful_neg}  "
          f"same-text pairs: {manifest['same_text_pairs']} "
          f"(label -1: {manifest['same_text_label_neg']})")
    return manifest


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--split", choices=("valid", "test", "all"), default="test",
                    help="which frozen split to materialise (default: test)")
    ap.add_argument("--xapi-per-query", type=int,
                    default=XAPI_PER_QUERY_DEFAULT,
                    help="cap on different-api gallery negatives per query "
                         f"(default {XAPI_PER_QUERY_DEFAULT})")
    args = ap.parse_args()

    verdicts = load_verdicts()
    gallery = load_gallery()
    splits = ("valid", "test") if args.split == "all" else (args.split,)
    for split_name in splits:
        build(split_name, verdicts, gallery, args.xapi_per_query)


if __name__ == "__main__":
    main()
