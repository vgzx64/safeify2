"""Scorer for the frozen real hold-out (see splits/README.md).

Modes
-----
(no args)                audit only: split sizes, leakage, verdict coverage,
                         pair/gallery stats — run before every experiment.
--pairs-preds FILE.csv   score a pair classifier on the selected split's pairs
                         CSV (default: test_pairs.csv).  FILE must contain a
                         `label` column with one value per row (aligned
                         positionally).  Reports accuracy / precision / recall
                         / F1 (macro), per-(api,pattern) recall on
                         gold-positive pairs, and FP rate on pairs whose BOTH
                         endpoints have verdict=N (irreplaceable) — the
                         FP-reduction target of notes/research/research-vectors.md.
--pairs-preds FILE.csv --full
                         same, but scores the ENLARGED set
                         <split>_pairs_full.csv (see make_eval_full.py):
                         per-stratum recall/FP, Wilson 95% intervals,
                         query-cluster bootstrap intervals, FP slices on
                         N-query x Y/M-gallery and both-N negatives, and
                         metrics excluding same-text pairs (corpus label
                         conflicts).
--retrieval-preds FILE   score retrieval against the fixed KB gallery.
                         FILE: JSON list of {"id": "<testdata rel_path>",
                         "pattern_id": N}. Reports top-1 pattern accuracy,
                         macro per-API recall, and recall/miss on verdict=N
                         queries.

Use `--split valid` to select epochs/thresholds; `--split test` is the
report-once evaluation.  Protocol (notes/research/synthetic-data-theory.md):
tune on `valid`, report `test` ONCE per model, never report a synthetic number.
"""

import argparse
import csv
import json
import math
import os
import random
import sys
from collections import defaultdict

SYNTH_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SPLITS_DIR = os.path.join(SYNTH_ROOT, "splits")


def load_json(name):
    with open(os.path.join(SPLITS_DIR, name), encoding="utf-8") as f:
        return json.load(f)


def safe_div(a, b):
    return a / b if b else 0.0


def prf(tp, fp, fn):
    p = safe_div(tp, tp + fp)
    r = safe_div(tp, tp + fn)
    f = safe_div(2 * p * r, p + r)
    return p, r, f


def manifest_name(split: str) -> str:
    """Test keeps the historical eval_manifest.json; other splits are named."""
    return "eval_manifest.json" if split == "test" else f"{split}_eval_manifest.json"


def audit(split: str = "test"):
    stats = load_json("stats.json")
    eval_m = load_json(manifest_name(split))

    print("=== split audit (frozen) ===")
    print(f"testdata: {stats['n_total']} files, usable {stats['n_usable']}, "
          f"excluded {len(stats['excluded'])}")
    print(f"train={stats['n_train']} valid={stats['n_valid']} "
          f"test={stats['n_test']} (70/10/20, seed {stats['seed']})")
    print(f"leakage: same_api={len(stats['leakage']['same_api_overlap'])} "
          f"cross_api={len(stats['leakage']['cross_api_overlap'])} "
          f"label_conflicts={len(stats['label_conflicts'])}")

    cells = {(r["api"], r["pattern"]) for r in stats["strata"]}
    test_cells = {(r["api"], r["pattern"]) for r in stats["strata"]
                  if r["test"] > 0}
    print(f"strata: {len(cells)} (api,pattern) cells, "
          f"{len(test_cells)} represented in test")
    print("verdict map: missing="
          f"{stats['verdict_map']['missing_verdict'] or 'none'}")

    print(f"eval: {eval_m['split']} snippets={eval_m['n_snippets']} "
          f"pairs={eval_m['n_pairs']} (pos={eval_m['n_pos']} "
          f"neg={eval_m['n_neg']})")
    print(f"gallery: {eval_m['gallery_entries']} entries / "
          f"{eval_m['gallery_apis']} apis")

    n_pairs = [p for p in eval_m["pairs"]
               if p["v1"] == "N" and p["v2"] == "N"]
    n_rows = [r for r in eval_m["rows"] if r["verdict"] == "N"]
    print(f"irreplaceable (verdict=N): {len(n_rows)} {split} snippets, "
          f"{len(n_pairs)} pairs with both endpoints N")
    if os.path.isfile(os.path.join(SPLITS_DIR, manifest_full_name(split))):
        fm = load_json(manifest_full_name(split))
        print(f"eval-full (enlarged): pairs={fm['n_pairs']} "
              f"(pos={fm['n_pos']} neg={fm['n_neg']}) "
              f"by_stratum={fm['by_stratum']} "
              f"both-N neg={fm['both_n_negatives']} "
              f"N-x-Y/M hard neg="
              f"{fm['n_query_vs_ym_hard_negatives']}")
    return stats, eval_m


def score_pairs(pred_path, split: str = "test"):
    _, eval_m = audit(split)
    with open(pred_path, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        if not reader.fieldnames or "label" not in reader.fieldnames:
            sys.exit(f"{pred_path}: need a CSV with a 'label' column")
        preds = [int(float(row["label"])) for row in reader]
    gold = [p["label"] for p in eval_m["pairs"]]
    if len(preds) != len(gold):
        sys.exit(f"{pred_path}: {len(preds)} predictions for "
                 f"{len(gold)} {split} pairs (row count must match)")

    tp = sum(1 for g, p in zip(gold, preds) if g == 1 and p == 1)
    tn = sum(1 for g, p in zip(gold, preds) if g == -1 and p == -1)
    fp = sum(1 for g, p in zip(gold, preds) if g == -1 and p == 1)
    fn = sum(1 for g, p in zip(gold, preds) if g == 1 and p == -1)
    acc = safe_div(tp + tn, len(gold))
    p1, r1, f1 = prf(tp, fp, fn)
    _, _, f0 = prf(tn, fn, fp)
    macro_f1 = (f1 + f0) / 2

    print(f"\n=== pair metrics ({split} split) ===")
    print(f"n={len(gold)}  accuracy={acc:.4f}  precision={p1:.4f} "
          f"recall={r1:.4f} f1={f1:.4f}  macro_f1={macro_f1:.4f}")
    print(f"confusion: tp={tp} fp={fp} fn={fn} tn={tn}")

    print("\nper-(api,pattern) recall on gold-positive pairs:")
    agg = defaultdict(lambda: [0, 0])
    for g, pr, meta in zip(gold, preds, eval_m["pairs"]):
        if g != 1:
            continue
        key = (meta["api"], meta["p1"])
        agg[key][1] += 1
        if pr == 1:
            agg[key][0] += 1
    per = [(safe_div(h, t), api, pat, h, t)
           for (api, pat), (h, t) in sorted(agg.items())]
    for r, api, pat, h, t in per:
        print(f"  {api}/p{pat}: {h}/{t} = {r:.3f}")
    macro_rec = safe_div(sum(r for r, *_ in per), len(per))
    print(f"macro per-pattern recall: {macro_rec:.4f}")

    # FP rate: pairs whose BOTH endpoints are irreplaceable (verdict=N) yet
    # gold = -1 (different patterns) but predicted same. Gold-positive N-N
    # pairs are not FP risk — the model SHOULD say they match.
    n_neg = [i for i, p in enumerate(eval_m["pairs"])
             if p["v1"] == "N" and p["v2"] == "N" and p["label"] == -1]
    n_fp = sum(1 for i in n_neg if preds[i] == 1)
    both = (f"{n_fp}/{len(n_neg)} = {safe_div(n_fp, len(n_neg)):.4f}"
            if n_neg else "n/a (no N-N label=-1 pairs in this split)")
    print(f"\nFP rate on verdict=N pairs (both endpoints irreplaceable): {both}")

    # FP on label--1 pairs touching verdict=N (missed-unsafe risk)
    n_any = [i for i, p in enumerate(eval_m["pairs"])
             if p["label"] == -1 and "N" in (p["v1"], p["v2"])]
    n_any_fp = sum(1 for i in n_any if preds[i] == 1)
    print(f"FP rate on label=-1 pairs touching verdict=N: "
          f"{n_any_fp}/{len(n_any)} = {safe_div(n_any_fp, len(n_any)):.4f}")
    return macro_f1


def manifest_full_name(split: str) -> str:
    return f"{split}_eval_manifest_full.json"


def wilson(k, n, z=1.96):
    """Wilson score interval for a binomial proportion."""
    if n == 0:
        return (0.0, 1.0)
    p = k / n
    d = 1 + z * z / n
    c = p + z * z / (2 * n)
    h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n))
    return (max(0.0, (c - h) / d), min(1.0, (c + h) / d))


def score_pairs_full(pred_path, split: str = "test"):
    """Score the enlarged stratified pair set (make_eval_full.py)."""
    eval_m = load_json(manifest_full_name(split))
    with open(pred_path, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        if not reader.fieldnames or "label" not in reader.fieldnames:
            sys.exit(f"{pred_path}: need a CSV with a 'label' column")
        preds = [int(float(row["label"])) for row in reader]
    gold = [p["label"] for p in eval_m["pairs"]]
    if len(preds) != len(gold):
        sys.exit(f"{pred_path}: {len(preds)} predictions for {len(gold)} "
                 f"{split} full pairs (row count must match)")
    meta = eval_m["pairs"]

    def confusion(idx):
        tp = sum(1 for i in idx if gold[i] == 1 and preds[i] == 1)
        tn = sum(1 for i in idx if gold[i] == -1 and preds[i] == -1)
        fp = sum(1 for i in idx if gold[i] == -1 and preds[i] == 1)
        fn = sum(1 for i in idx if gold[i] == 1 and preds[i] == -1)
        return tp, tn, fp, fn

    def report(idx, title):
        tp, tn, fp, fn = confusion(idx)
        n = len(idx)
        acc = safe_div(tp + tn, n)
        lo, hi = wilson(tp + tn, n)
        p1, r1, f1 = prf(tp, fp, fn)
        _, _, f0 = prf(tn, fn, fp)
        macro_f1 = (f1 + f0) / 2
        print(f"\n=== {title} ({split} full) ===")
        print(f"n={n} (pos={tp + fn} neg={tn + fp})  "
              f"accuracy={acc:.4f} [{lo:.4f}, {hi:.4f}]  macro_f1={macro_f1:.4f}")
        print(f"confusion: tp={tp} fp={fp} fn={fn} tn={tn}")
        return acc, macro_f1

    all_idx = list(range(len(gold)))
    report(all_idx, "pair metrics (ALL strata)")

    print("\nper-stratum (recall on positive strata, FP rate on negative):")
    for s in ("POS-QG", "POS-QQ", "NEG-HARD-QG", "NEG-HARD-QQ", "NEG-XAPI-QG"):
        idx = [i for i in all_idx if meta[i]["stratum"] == s]
        if not idx:
            print(f"  {s}: n=0")
            continue
        if s.startswith("POS"):
            k = sum(1 for i in idx if preds[i] == 1)
            lo, hi = wilson(k, len(idx))
            print(f"  {s}: recall {k}/{len(idx)} = {safe_div(k, len(idx)):.4f} "
                  f"[{lo:.4f}, {hi:.4f}]")
        else:
            k = sum(1 for i in idx if preds[i] == 1)
            lo, hi = wilson(k, len(idx))
            print(f"  {s}: FP {k}/{len(idx)} = {safe_div(k, len(idx)):.4f} "
                  f"[{lo:.4f}, {hi:.4f}]")

    print("\nper-(api,pattern) recall on gold-positive pairs:")
    agg = defaultdict(lambda: [0, 0])
    for i in all_idx:
        if gold[i] != 1:
            continue
        key = (meta[i]["api"], meta[i]["p1"])
        agg[key][1] += 1
        agg[key][0] += preds[i] == 1
    for (api, pat), (h, t) in sorted(agg.items()):
        print(f"  {api}/p{pat}: {h}/{t} = {safe_div(h, t):.3f}")
    macro_rec = safe_div(sum(safe_div(h, t) for h, t in agg.values()), len(agg))
    print(f"macro per-pattern recall: {macro_rec:.4f}")

    print("\nsafety slices (label=-1 pairs, predicted same):")
    for title, pred in (
        ("N query x Y/M gallery, same api (NEG-HARD-QG) — "
         "recommend-on-irreplaceable",
         lambda m: m["stratum"] == "NEG-HARD-QG"
         and m["v1"] == "N" and m["v2"] in ("Y", "M")),
        ("both endpoints N", lambda m: m["v1"] == "N" and m["v2"] == "N"),
        ("any endpoint N", lambda m: "N" in (m["v1"], m["v2"])),
    ):
        idx = [i for i in all_idx if gold[i] == -1 and pred(meta[i])]
        k = sum(1 for i in idx if preds[i] == 1)
        lo, hi = wilson(k, len(idx))
        print(f"  {title}: {k}/{len(idx)} = {safe_div(k, len(idx)):.4f} "
              f"[{lo:.4f}, {hi:.4f}]")

    clean = [i for i in all_idx if not meta[i]["same_text"]]
    if len(clean) != len(all_idx):
        report(clean, "pair metrics EXCLUDING same-text pairs")
    else:
        print("\nno same-text pairs in this split")

    # query-cluster bootstrap: pairs sharing a query are correlated, so the
    # effective sample is the set of queries, not the pair count.
    by_q = defaultdict(list)
    for i in all_idx:
        by_q[meta[i]["q"]].append(i)
    queries = sorted(by_q)
    rng = random.Random(1234)
    accs, f1s = [], []
    for _ in range(2000):
        sample = [rng.choice(queries) for _ in queries]
        idx = [i for q in sample for i in by_q[q]]
        tp, tn, fp, fn = confusion(idx)
        accs.append(safe_div(tp + tn, len(idx)))
        _, _, f1b = prf(tp, fp, fn)
        _, _, f0b = prf(tn, fn, fp)
        f1s.append((f1b + f0b) / 2)
    accs.sort(), f1s.sort()
    print(f"\nquery-cluster bootstrap 95% intervals "
          f"({len(queries)} queries, B=2000, seed 1234):")
    print(f"  accuracy [{accs[49]:.4f}, {accs[1949]:.4f}]  "
          f"macro_f1 [{f1s[49]:.4f}, {f1s[1949]:.4f}]")
    print("  (pair-level Wilson intervals above ignore this clustering; "
          "the bootstrap is the honest one)")


def score_retrieval(pred_path, split: str = "test"):
    _, eval_m = audit(split)
    with open(pred_path, encoding="utf-8") as f:
        raw = json.load(f)
    pred_map = {r["id"]: int(r["pattern_id"]) for r in raw}

    rows = eval_m["rows"]
    hits = 0
    per_api = defaultdict(lambda: [0, 0])
    n_total = n_hit = 0
    for row in rows:
        if row["rel_path"] not in pred_map:
            sys.exit(f"missing prediction for {row['rel_path']}")
        ok = pred_map[row["rel_path"]] == row["pattern_id"]
        hits += ok
        per_api[row["api"]][0] += ok
        per_api[row["api"]][1] += 1
        if row["verdict"] == "N":
            n_total += 1
            n_hit += ok
    acc = safe_div(hits, len(rows))
    macro = safe_div(sum(safe_div(h, t) for h, t in per_api.values()),
                     len(per_api))
    print(f"\n=== retrieval metrics ({split} queries vs fixed KB gallery) ===")
    print(f"queries={len(rows)}  top-1 pattern accuracy={acc:.4f}  "
          f"macro per-API recall={macro:.4f}")
    print(f"recall on verdict=N (irreplaceable) queries: "
          f"{n_hit}/{n_total} = {safe_div(n_hit, n_total):.4f}  "
          f"(miss rate = {1 - safe_div(n_hit, n_total):.4f})")
    for api in sorted(per_api):
        h, t = per_api[api]
        print(f"  {api}: {h}/{t} = {safe_div(h, t):.3f}")
    return acc


def main():
    ap = argparse.ArgumentParser(
        description="Frozen-split scorer; see module docstring.")
    ap.add_argument("--split", choices=("valid", "test"), default="test",
                    help="which frozen split to score (default: test)")
    ap.add_argument("--pairs-preds",
                    help="CSV with a 'label' column aligned to <split>_pairs.csv")
    ap.add_argument("--full", action="store_true",
                    help="with --pairs-preds: score <split>_pairs_full.csv "
                         "(enlarged set from make_eval_full.py)")
    ap.add_argument("--retrieval-preds",
                    help="JSON list of {id, pattern_id} predictions")
    args = ap.parse_args()
    if args.pairs_preds:
        if args.full:
            score_pairs_full(args.pairs_preds, args.split)
        else:
            score_pairs(args.pairs_preds, args.split)
    elif args.retrieval_preds:
        score_retrieval(args.retrieval_preds, args.split)
    else:
        audit(args.split)


if __name__ == "__main__":
    main()
