"""Pair-level ranker baseline: is (old, candidate new) a valid safe replacement?

The suggestion tool would generate candidate fixes from the mechanism/KB layer
and then rank them. This is the learning problem that ranker solves, and it is
much better posed than predicting the mechanism from the old snippet alone: the
candidate fix is an input.

Labels are objective:

  positive        a real audited old->new pair for a Y row
  natural neg     an M/N row's old->new, where the new snippet keeps unsafe code
  hard neg        a Y old paired with another Y's new snippet from a different
                  repository: safe code, but not a replacement for this site

Natural negatives are mostly the trivial "unsafe still present" shortcut; hard
negatives are the semantic test. Both are reported separately.

Protocol: fit on train pairs, score the frozen valid split once. The valid hard
negatives use donors from train repositories only, so valid rows are disjoint
from the donor pool. Test pairs are never scored.

Writes out/baseline_pair_v0.1.{json,md}.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections import Counter, defaultdict
from pathlib import Path

import numpy as np
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import average_precision_score, roc_auc_score
from sklearn.model_selection import StratifiedGroupKFold
from sklearn.base import BaseEstimator, TransformerMixin
from sklearn.pipeline import FeatureUnion, Pipeline

from mechanism_rules import UNSAFE

OUT = Path(__file__).resolve().parent / "out"
DATASET = OUT / "mechanism_dataset_v05.jsonl"
SEP = "\n<<<CANDIDATE>>>\n"


def load():
    rows = [json.loads(x) for x in DATASET.open() if x.strip()]
    train = [r for r in rows if r["split"] == "train"]
    valid = [r for r in rows if r["split"] == "valid"]
    test = [r for r in rows if r["split"] == "test"]
    assert (len(valid), len(test)) == (87, 130)
    return train, valid


def pair_text(old: str, new: str) -> str:
    return old + SEP + new


SEED_STR = "safeify-pair-v01"


def donor_for(row, pool, mode="random", seed_str=SEED_STR):
    """Deterministic donor Y row: another repository, optionally same mechanism."""
    h = int(hashlib.sha256((seed_str + row["id"] + mode).encode()).hexdigest(), 16)
    base = [p for p in pool if p["repo_key"] != row["repo_key"]]
    if mode == "mechanism":
        same = [p for p in base if p["mechanism"] == row["mechanism"]]
        base = same or base
    return base[h % len(base)] if base else None


def build_pairs(rows, donors, with_natural=True, donor_mode="random"):
    pairs = []
    for r in rows:
        y = r["mechanism"] != "retain"
        if y:
            pairs.append({"x": r["old_snippet"], "new": r["safe_snippet"],
                          "y": 1, "kind": "pos", "repo": r["repo_key"]})
            d = donor_for(r, donors, donor_mode)
            if d is not None:
                pairs.append({"x": r["old_snippet"], "new": d["safe_snippet"],
                              "y": 0, "kind": "hard", "repo": r["repo_key"]})
        elif with_natural:
            pairs.append({"x": r["old_snippet"], "new": r["safe_snippet"],
                          "y": 0, "kind": "natural", "repo": r["repo_key"]})
    return pairs


SAFE_MARKERS = ("get(", "get (", ".get_mut(", "try_into", ".parse(", "resize(",
                "resize_with(", ".truncate(", ".reserve(", "copy_from_slice",
                "from_utf8", "from_bytes_with_nul", "chunks", "windows(",
                "to_ne_bytes", "from_ne_bytes", "MaybeUninit", "Cell",
                "RefCell", "Mutex", "RwLock", "Pin::new")


def idents(text: str) -> set[str]:
    return set(re.findall(r"[A-Za-z_][A-Za-z0-9_]*", text or ""))


class PairNumeric(BaseEstimator, TransformerMixin):
    """Explicit pairwise features the char n-grams cannot express cleanly."""

    def fit(self, x, y=None):
        return self

    def transform(self, x):
        import numpy as np
        out = []
        for row in x:
            a, b = idents(row["old"]), idents(row["new"])
            inter = len(a & b)
            union = max(1, len(a | b))
            out.append([
                float(bool(UNSAFE.search(row["new"]))),
                float(bool(UNSAFE.search(row["old"]))),
                inter / union,
                inter / max(1, min(len(a), len(b))),
                min(len(row["new"]), len(row["old"])) / max(1, len(row["new"]), len(row["old"])),
                float(any(m in row["new"] for m in SAFE_MARKERS)),
            ])
        return np.asarray(out, dtype=float)


def pair_model(numeric=True):
    branches = [("tfidf", Pipeline([
        ("sel", _Sel()),
        ("tfidf", TfidfVectorizer(analyzer="char_wb", ngram_range=(2, 5),
                                  sublinear_tf=True, min_df=2)),
    ]))]
    if numeric:
        branches.append(("num", PairNumeric()))
    return Pipeline([
        ("feat", FeatureUnion(branches)),
        ("clf", LogisticRegression(class_weight="balanced", max_iter=3000,
                                   C=1.0, random_state=0)),
    ])


class _Sel(BaseEstimator, TransformerMixin):
    def fit(self, x, y=None):
        return self

    def transform(self, x):
        return [row["text"] for row in x]


def evaluate(pairs, kind=None):
    ys = np.array([p["y"] for p in pairs])
    if ys.min() == ys.max():
        return None
    return {"n": int(len(ys)), "positives": int(ys.sum())}


def metrics(pairs, proba):
    y = np.array([p["y"] for p in pairs])
    out = {"n": len(y), "positives": int(y.sum())}
    if y.min() != y.max():
        out["roc_auc"] = float(roc_auc_score(y, proba))
        out["average_precision"] = float(average_precision_score(y, proba))
    out["accuracy_at_0.5"] = float(((proba >= 0.5) == (y == 1)).mean())
    return out


def as_rows(pairs):
    return [{"text": pair_text(p["x"], p["new"]), "old": p["x"], "new": p["new"]}
            for p in pairs]


def cv_scores(pairs, numeric=True):
    rows = as_rows(pairs)
    x = rows
    y = np.array([p["y"] for p in pairs])
    groups = np.array([p["repo"] for p in pairs])
    skf = StratifiedGroupKFold(n_splits=5, shuffle=True, random_state=0)
    oof = np.zeros(len(y))
    for tr, te in skf.split(x, y, groups):
        m = pair_model(numeric)
        m.fit([x[i] for i in tr], y[tr])
        oof[te] = m.predict_proba([x[i] for i in te])[:, 1]
    out = metrics(pairs, oof)
    hard = [p for p in pairs if p["kind"] in ("pos", "hard")]
    idx = [i for i, p in enumerate(pairs) if p["kind"] in ("pos", "hard")]
    if hard:
        h = metrics(hard, oof[idx])
        out["hard_negatives"] = h
    natural = [p for p in pairs if p["kind"] in ("pos", "natural")]
    idx = [i for i, p in enumerate(pairs) if p["kind"] in ("pos", "natural")]
    if natural:
        out["natural_negatives"] = metrics(natural, oof[idx])
    out["precision_at10"] = float(np.mean(y[np.argsort(-oof)[:10]])) if len(y) >= 10 else None
    return out


def perturb(new: str, kind: str) -> str | None:
    """Break a real replacement while keeping identifier vocabulary similar."""
    lines = new.splitlines()
    if kind == "drop_guard":
        for i, line in enumerate(lines):
            if re.search(r"\b(if|assert|assert_eq|checked_|\?)\b", line) and line.strip():
                return "\n".join(lines[:i] + lines[i + 1:])
        return None
    if kind == "swap_ident":
        ids = [m for m in re.findall(r"[A-Za-z_][A-Za-z0-9_]*", new)
               if m not in ("let", "mut", "unsafe", "fn", "pub", "use", "self", "Self",
                            "impl", "match", "if", "else", "return", "Ok", "Err", "Some",
                            "None", "true", "false")]
        if len(ids) < 2:
            return None
        a, b = ids[0], ids[1]
        if a == b:
            return None
        tmp = "__SWAP__"
        out = re.sub(rf"\b{re.escape(a)}\b", tmp, new)
        out = re.sub(rf"\b{re.escape(b)}\b", a, out)
        return re.sub(rf"\b{re.escape(tmp)}\b", b, out)
    if kind == "change_index":
        m = re.search(r"\b(\d+)\b", new)
        if not m:
            return None
        v = int(m.group(1))
        return new[:m.start()] + str(v + 1) + new[m.end():]
    return None


def near_miss_eval(model, valid_y):
    """Same old snippet, real candidate vs a perturbed one; did the model keep them apart?"""
    rows_real, rows_pert, kinds = [], [], []
    for r in valid_y:
        for kind in ("drop_guard", "swap_ident", "change_index"):
            cand = perturb(r["safe_snippet"], kind)
            if not cand or not cand.strip() or UNSAFE.search(cand):
                continue
            rows_real.append({"text": pair_text(r["old_snippet"], r["safe_snippet"]),
                              "old": r["old_snippet"], "new": r["safe_snippet"]})
            rows_pert.append({"text": pair_text(r["old_snippet"], cand),
                              "old": r["old_snippet"], "new": cand})
            kinds.append(kind)
    if not rows_real:
        return None
    p_real = model.predict_proba(rows_real)[:, 1]
    p_pert = model.predict_proba(rows_pert)[:, 1]
    wins = float(np.mean(p_real > p_pert))
    return {"comparisons": len(rows_real), "real_above_perturbed_rate": wins,
            "mean_margin": float(np.mean(p_real - p_pert)),
            "by_kind": {k: float(np.mean([(p_real[i] > p_pert[i]) for i, kk in enumerate(kinds) if kk == k]))
                        for k in set(kinds)}}


def trivial_baseline(train, valid):
    """One-feature baseline: does the new snippet still contain unsafe code?"""
    def feats(rows):
        return [[1.0 if UNSAFE.search(r["safe_snippet"]) else 0.0] for r in rows]
    y = np.array([0 if r["mechanism"] == "retain" else 1 for r in train])
    clf = LogisticRegression(class_weight="balanced", max_iter=1000)
    clf.fit(feats(train), y)
    proba = clf.predict_proba(feats(valid))[:, 1]
    yv = np.array([0 if r["mechanism"] == "retain" else 1 for r in valid])
    return {"roc_auc_natural": float(roc_auc_score(yv, proba))}


def main():
    train, valid = load()
    train_y = [r for r in train if r["mechanism"] != "retain"]
    valid_y = [r for r in valid if r["mechanism"] != "retain"]

    # train pairs: positives + natural negatives + hard negatives (donors from train Y)
    configs = {}
    for mode in ("random", "mechanism"):
        configs[mode] = {
            "train": build_pairs(train, train_y, donor_mode=mode),
            "valid": build_pairs(valid, train_y, donor_mode=mode),
        }

    # ablation on the mechanism/with_natural configuration
    mech_cfg = configs["mechanism"]
    abl_pairs = mech_cfg["train"]
    abl_valid = mech_cfg["valid"]
    idx_h = [i for i, p in enumerate(abl_valid) if p["kind"] in ("pos", "hard")]
    idx_n = [i for i, p in enumerate(abl_valid) if p["kind"] in ("pos", "natural")]

    def fit_score(m):
        m.fit(as_rows(abl_pairs), [p["y"] for p in abl_pairs])
        pr = m.predict_proba(as_rows(abl_valid))[:, 1]
        return {"valid_hard_auc": metrics([abl_valid[i] for i in idx_h], pr[idx_h]).get("roc_auc"),
                "valid_natural_auc": metrics([abl_valid[i] for i in idx_n], pr[idx_n]).get("roc_auc")}

    from sklearn.pipeline import Pipeline as _P
    abl = {
        "full": fit_score(pair_model(True)),
        "tfidf_only": fit_score(pair_model(False)),
        "numeric_only": fit_score(_P([("num", PairNumeric()),
                                      ("clf", LogisticRegression(class_weight="balanced",
                                                                 max_iter=1000, C=1.0))])),
    }
    # near-miss test: the ranker must prefer the real candidate over a perturbed
    # one for the SAME old snippet (model trained on the mechanism config)
    mech_model = pair_model(True)
    mech_model.fit(as_rows(mech_cfg["train"]), [p["y"] for p in mech_cfg["train"]])
    results = {
        "near_miss_mechanism_with_natural": near_miss_eval(mech_model, valid_y),
        "ablation_mechanism_with_natural": abl,
        "pair_counts": {m: {split: dict(Counter(p["kind"] for p in cfg[split]))
                            for split in ("train", "valid")}
                        for m, cfg in configs.items()},
        "trivial_unsafe_presence": trivial_baseline(train, valid),
    }

    for mode, cfg in configs.items():
        train_pairs, valid_pairs = cfg["train"], cfg["valid"]
        for tag, pairs_train in (("with_natural", train_pairs),
                                 ("hard_only", [p for p in train_pairs
                                                if p["kind"] != "natural"])):
            model = pair_model(True)
            model.fit(as_rows(pairs_train), [p["y"] for p in pairs_train])
            proba_v = model.predict_proba(as_rows(valid_pairs))[:, 1]
            res = {"cv": cv_scores(pairs_train),
                   "valid_all": metrics(valid_pairs, proba_v)}
            idx_hard = [i for i, p in enumerate(valid_pairs) if p["kind"] in ("pos", "hard")]
            res["valid_hard"] = metrics([valid_pairs[i] for i in idx_hard], proba_v[idx_hard])
            idx_nat = [i for i, p in enumerate(valid_pairs) if p["kind"] in ("pos", "natural")]
            res["valid_natural"] = metrics([valid_pairs[i] for i in idx_nat], proba_v[idx_nat])
            results[f"{mode}/{tag}"] = res
            print(f"{mode}/{tag}: cv AUC {res['cv'].get('roc_auc'):.3f} | "
                  f"valid hard AUC {res['valid_hard'].get('roc_auc'):.3f} | "
                  f"valid natural AUC {res['valid_natural'].get('roc_auc'):.3f}")

    json.dump(results, open(OUT / "baseline_pair_v0.1.json", "w"),
              indent=2, ensure_ascii=False)
    md = ["# Pair-level ranker baseline (v0.1)", "",
          "Given `(old_snippet, candidate_new)`, rank whether the candidate is a",
          "valid safe replacement. Valid rows are scored once; test is sealed.", "",
          "Two hard-negative constructions: `random` donors from other repositories,",
          "and `mechanism` donors from the same mechanism class (harder, because the",
          "API vocabulary overlaps).", "",
          "| hard negatives | training mix | CV AUC | valid hard-negative AUC | valid natural-negative AUC |",
          "|---|---|---:|---:|---:|"]
    for tag in results:
        if "/" not in tag:
            continue
        r = results[tag]
        md.append(f"| {tag} | {r['cv'].get('roc_auc', float('nan')):.3f} | "
                  f"{r['valid_hard'].get('roc_auc', float('nan')):.3f} | "
                  f"{r['valid_natural'].get('roc_auc', float('nan')):.3f} |")
    nm = results.get("near_miss_mechanism_with_natural")
    if nm:
        md += ["", "Near-miss test (same old snippet; real candidate vs perturbed candidate):", "",
               f"real candidate ranked above its perturbed twin in {nm['real_above_perturbed_rate']:.3f} "
               f"of {nm['comparisons']} comparisons (chance 0.5), mean margin {nm['mean_margin']:+.3f}", "",
               "| perturbation | win rate |", "|---|---:|"]
        for k, v in sorted(nm["by_kind"].items()):
            md.append(f"| {k} | {v:.3f} |")
    md += ["", "Ablation (mechanism hard negatives, with natural negatives):", "",
           "| features | valid hard AUC | valid natural AUC |", "|---|---:|---:|"]
    for name, a in results["ablation_mechanism_with_natural"].items():
        md.append(f"| {name} | {a['valid_hard_auc']:.3f} | {a['valid_natural_auc']:.3f} |")
    md += ["", f"Trivial single-feature baseline (is `unsafe` present in the candidate?): "
           f"natural-negative AUC {results['trivial_unsafe_presence']['roc_auc_natural']:.3f}.", "",
           "Valid hard negatives pair a valid Y row's old snippet with a train Y row's",
           "candidate from a different repository: safe code, wrong replacement.", "",
           "Pair counts:", "",
           "| split | positives | natural negatives | hard negatives |",
           "|---|---:|---:|---:|"]
    for split in ("train", "valid"):
        c = results["pair_counts"]["random"][split]
        md.append(f"| {split} | {c.get('pos', 0)} | {c.get('natural', 0)} | {c.get('hard', 0)} |")
    (OUT / "baseline_pair_v0.1.md").write_text("\n".join(md) + "\n")
    print(f"\nwrote {OUT}/baseline_pair_v0.1.json and .md")


if __name__ == "__main__":
    main()
