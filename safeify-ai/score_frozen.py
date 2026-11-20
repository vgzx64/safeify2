"""Score a safeify-ai JSON report on the frozen real test split.

Usage (from the repository root):
  python safeify-ai/score_frozen.py --report safeify-ai/out/nirm3_eval_lsp.json
  python safeify-ai/score_frozen.py --report safeify-ai/out/nirm3_eval_lsp.json \\
      --report2 safeify-ai/out/nirm3_eval_nolsp.json

Ground truth: safeify-data/synth/splits/eval_manifest.json.
"""

from __future__ import annotations

import argparse
import json
import random
import sys
from collections import Counter, defaultdict
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
MANIFEST = REPO / "safeify-data" / "synth" / "splits" / "eval_manifest.json"

sys.path.insert(0, str(REPO / "safeify-ai"))
from verdict import FAMILY  # noqa: E402  (family table for breakdowns)

VS = ("Y", "M", "N")


def rel_testdata(path: str) -> str | None:
    """abs/rel report path -> testdata-relative path (e.g. Box::from_raw/1-2.rs)."""
    parts = Path(path).resolve().parts
    for i, p in enumerate(parts):
        if p == "testdata":
            return "/".join(parts[i + 1:])
    return None


def load_gold() -> dict[str, dict]:
    data = json.loads(MANIFEST.read_text())
    return {r["rel_path"]: r for r in data["rows"]}


def load_gold_split(split: str) -> dict[str, dict]:
    """Gold for train/valid from splits/manifest.json + kb_verdicts.json
    (test uses eval_manifest.json for exact protocol consistency)."""
    if split == "test":
        return load_gold()
    m = json.loads((MANIFEST.parent / "manifest.json").read_text())
    kb = json.loads((MANIFEST.parent / "kb_verdicts.json").read_text())["apis"]
    members = set((MANIFEST.parent / f"{split}.txt").read_text().splitlines())
    gold: dict[str, dict] = {}
    for rec in m["files"]:
        rel = rec["rel_path"]
        if rel not in members or not rec.get("usable"):
            continue
        v = kb.get(rec["api"], {}).get(str(rec["pattern_id"]))
        if v is None:
            continue  # no gold verdict for this cell (documented in stats)
        gold[rel] = {"rel_path": rel, "api": rec["api"],
                     "pattern_id": rec["pattern_id"], "verdict": v}
    return gold


def score(report_path: str, gold: dict[str, dict]) -> dict:
    rep = json.loads(Path(report_path).read_text())
    reports = rep["reports"]

    conf = {p: Counter() for p in VS}          # gold -> pred counts
    per_api = defaultdict(lambda: [0, 0])       # api -> [correct, total]
    unmatched_files: list[str] = []
    api_mismatch: list[str] = []
    n_files = n_sinks = n_evaluated = 0
    y_pred = y_pred_gold_y = 0
    n_gold = n_gold_pred_n = 0
    fp_on_n = 0
    hint_total = hint_correct = 0
    hint_wrong: list[tuple[str, str, int, int]] = []
    per_family = defaultdict(lambda: [0, 0])       # family -> [correct, total]
    rows: list[tuple[str, str, str, str]] = []     # (file, gold, pred, conf)

    for r in reports:
        n_files += 1
        rel = rel_testdata(r["file"])
        if rel is None or rel not in gold:
            unmatched_files.append(str(r["file"]))
            continue
        g = gold[rel]
        gv = g["verdict"]
        for s in r["sinks"]:
            n_sinks += 1
            if s["api"] != g["api"]:
                api_mismatch.append(f"{rel}: sink {s['api']} != gold {g['api']}")
                continue
            n_evaluated += 1
            pv = s["verdict"]["v"]
            conf[gv][pv] += 1
            rows.append((rel, gv, pv, s["verdict"].get("confidence", "low")))
            per_api[g["api"]][1] += 1
            if pv == gv:
                per_api[g["api"]][0] += 1
            fam = FAMILY.get(s["api"], "rawmem")
            per_family[fam][1] += 1
            if pv == gv:
                per_family[fam][0] += 1
            if pv == "Y":
                y_pred += 1
                if gv == "Y":
                    y_pred_gold_y += 1
                if gv == "N":
                    fp_on_n += 1
            if gv == "N":
                n_gold += 1
                if pv == "N":
                    n_gold_pred_n += 1
            hint = s["verdict"]["pattern_hint"]
            if hint is not None:
                hint_total += 1
                if hint == g["pattern_id"]:
                    hint_correct += 1
                else:
                    hint_wrong.append((rel, s["api"], hint, g["pattern_id"]))

    correct = sum(conf[v].get(v, 0) for v in VS)
    n_claim = sum(conf[g].get("N", 0) for g in VS)
    y_claim = sum(conf[g].get("Y", 0) for g in VS)
    m_claim = sum(conf[g].get("M", 0) for g in VS)
    n_total = n_claim + y_claim + m_claim
    return {
        "report": report_path,
        "files": n_files, "sinks": n_sinks, "evaluated": n_evaluated,
        "unmatched_files": unmatched_files, "api_mismatch": api_mismatch,
        "conf": {p: dict(conf[p]) for p in VS},
        "rows": rows,
        "accuracy": correct / n_evaluated if n_evaluated else 0.0,
        "fp_on_n": fp_on_n, "n_gold": n_gold,
        "n_recall": n_gold_pred_n / n_gold if n_gold else None,
        "y_pred": y_pred,
        "y_precision": y_pred_gold_y / y_pred if y_pred else None,
        # decisiveness: share of sinks given a real Y/N claim vs abstention
        "claim_rate": (y_claim + n_claim) / n_total if n_total else 0.0,
        "m_rate": m_claim / n_total if n_total else 0.0,
        "hint_total": hint_total, "hint_correct": hint_correct,
        "hint_wrong": hint_wrong,
        "per_api": {a: (c, t, c / t) for a, (c, t) in sorted(per_api.items())},
        "per_family": {f: (c, t, c / t) for f, (c, t) in sorted(per_family.items())},
    }


def per_class(conf: dict) -> dict:
    """Per-class precision/recall/F1 from a gold->pred confusion table."""
    out = {}
    for c in VS:
        tp = conf[c].get(c, 0)
        pred_c = sum(conf[g].get(c, 0) for g in VS)
        gold_c = sum(conf[c].values())
        p = tp / pred_c if pred_c else None
        r = tp / gold_c if gold_c else None
        f1 = 2 * p * r / (p + r) if (p and r) else None
        out[c] = {"tp": tp, "pred": pred_c, "gold": gold_c,
                  "p": p, "r": r, "f1": f1}
    return out


def macro_f1(conf: dict) -> float:
    """Macro-F1 over classes that have gold support (Y/M/N)."""
    f1s = [m["f1"] for m in per_class(conf).values()
           if m["f1"] is not None]
    return sum(f1s) / len(f1s) if f1s else 0.0


def _conf_from(rows) -> dict:
    conf = {p: Counter() for p in VS}
    for _, gv, pv, _ in rows:
        conf[gv][pv] += 1
    return conf


def bootstrap_ci(rows, n_boot: int = 2000, seed: int = 1234) -> dict:
    """95% percentile intervals, resampling FILES (cluster bootstrap)."""
    by_file: dict[str, list] = defaultdict(list)
    for r in rows:
        by_file[r[0]].append(r)
    files = sorted(by_file)
    rng = random.Random(seed)
    stats = {"accuracy": [], "fp_on_n": [], "recall_n": [], "macro_f1": []}
    for _ in range(n_boot):
        conf = {p: Counter() for p in VS}
        n = 0
        for _ in range(len(files)):
            for _, gv, pv, _ in by_file[files[rng.randrange(len(files))]]:
                conf[gv][pv] += 1
                n += 1
        correct = sum(conf[v].get(v, 0) for v in VS)
        n_gold = sum(conf["N"].values())
        stats["accuracy"].append(correct / n if n else 0.0)
        stats["fp_on_n"].append(conf["N"].get("Y", 0) / n_gold if n_gold else 0.0)
        stats["recall_n"].append(conf["N"].get("N", 0) / n_gold if n_gold else 0.0)
        stats["macro_f1"].append(macro_f1(conf))
    out = {}
    for k, vals in stats.items():
        vals.sort()
        out[k] = (vals[int(0.025 * len(vals))],
                  vals[min(len(vals) - 1, int(0.975 * len(vals)))])
    return out


def risk_coverage(rows) -> list[tuple[str, int, int, float, float]]:
    """(level, claims, errors, coverage, risk) with high-confidence first.

    A verdict is a *claim* when it is Y or N; M is an abstention. Coverage is
    the share of evaluated sinks claimed, risk the error rate among claims.
    """
    total = len(rows)
    levels = [("high", [r for r in rows if r[2] in "YN" and r[3] == "high"]),
              ("all", [r for r in rows if r[2] in "YN"])]
    out = []
    for name, claimed in levels:
        errors = sum(1 for _, gv, pv, _ in claimed if gv != pv)
        cov = len(claimed) / total if total else 0.0
        risk = errors / len(claimed) if claimed else 0.0
        out.append((name, len(claimed), errors, cov, risk))
    return out


def show(out: dict) -> None:
    print(f"\n=== {out['report']} ===")
    print(f"files={out['files']} sinks={out['sinks']} "
          f"evaluated={out['evaluated']} "
          f"unmatched_files={len(out['unmatched_files'])} "
          f"api_mismatch={len(out['api_mismatch'])}")
    print("\nconfusion (rows=gold, cols=pred):")
    print(f"{'gold':>5} {'Y':>5} {'M':>5} {'N':>5}")
    for g in VS:
        row = out["conf"][g]
        print(f"{g:>5} " + " ".join(f"{row.get(p, 0):>5}" for p in VS))
    acc = out["accuracy"]
    print(f"\naccuracy: {acc:.4f} "
          f"({sum(out['conf'][v].get(v, 0) for v in VS)}/{out['evaluated']})")
    rec = out["n_recall"]
    print(f"FP-on-N (gold N -> pred Y): {out['fp_on_n']}/{out['n_gold']}"
          + (f"  recall_N={rec:.4f}" if rec is not None else ""))
    if out["y_precision"] is not None:
        print(f"Y precision: {out['y_precision']:.4f} ({out['y_pred']} Y predictions)")
    print(f"claim_rate: {out['claim_rate']:.4f}  (M-rate {out['m_rate']:.4f} — "
          f"abstentions)")
    print("\nper-class (gold, pred, tp, precision, recall, F1):")
    for c, m in per_class(out["conf"]).items():
        def f(x):
            return "n/a" if x is None else f"{x:.4f}"
        print(f"  {c}: gold={m['gold']:<3d} pred={m['pred']:<3d} "
              f"tp={m['tp']:<3d} P={f(m['p'])} R={f(m['r'])} F1={f(m['f1'])}")
    print(f"macro-F1: {macro_f1(out['conf']):.4f}")
    print("\nrisk-coverage (claim = Y/N; M abstains; high-confidence first):")
    for name, k, err, cov, risk in risk_coverage(out["rows"]):
        print(f"  {name:4s} claims={k:<3d} errors={err:<2d} "
              f"coverage={cov:.4f} risk={risk:.4f}")
    print(f"pattern claims: {out['hint_total']}/{out['evaluated']} sinks, "
          f"correct={out['hint_correct']}"
          + (f" ({out['hint_correct']/out['hint_total']:.4f})" if out["hint_total"] else ""))
    for rel, api, hint, gold_pid in out["hint_wrong"]:
        print(f"  wrong hint: {rel} {api} hint=p{hint} gold=p{gold_pid}")
    print("\nper-family accuracy (correct/total):")
    for f, (c, t, r) in out["per_family"].items():
        print(f"  {f:14s} {c:3d}/{t:<3d} {r:.3f}")
    print("\nper-API accuracy (correct/total):")
    for a, (c, t, r) in out["per_api"].items():
        print(f"  {a:24s} {c:3d}/{t:<3d} {r:.3f}")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--report", required=True)
    ap.add_argument("--report2", help="second report for a delta summary")
    ap.add_argument("--split", default="test", choices=("test", "valid", "train"),
                    help="gold split to score against (default: test)")
    ap.add_argument("--bootstrap", type=int, default=2000,
                    help="file-clustered bootstrap reps for 95%% CIs "
                         "(0 disables)")
    args = ap.parse_args()

    if not MANIFEST.exists():
        print(f"missing gold manifest: {MANIFEST}", file=sys.stderr)
        return 1
    gold = load_gold_split(args.split)
    print(f"gold rows: {len(gold)} (split={args.split})")

    out1 = score(args.report, gold)
    show(out1)
    if args.report2:
        out2 = score(args.report2, gold)
        show(out2)
        print("\n=== delta (report - report2) ===")
        print(f"accuracy: {out1['accuracy']:.4f} vs {out2['accuracy']:.4f}")
        print(f"FP-on-N:  {out1['fp_on_n']} vs {out2['fp_on_n']}")
        print(f"pattern claims: {out1['hint_total']} vs {out2['hint_total']}")
    if args.bootstrap:
        for out in ([out1] + ([out2] if args.report2 else [])):
            ci = bootstrap_ci(out["rows"], args.bootstrap)
            print(f"\n95% CI, file-clustered bootstrap ({args.bootstrap} reps) "
                  f"— {out['report']}:")
            for k, (lo, hi) in ci.items():
                print(f"  {k:9s} [{lo:.4f}, {hi:.4f}]")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

