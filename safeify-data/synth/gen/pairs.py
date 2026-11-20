"""Build BERT/SNN training pair CSVs (baseline-identical format).

Outputs (all with the shipped header `,text1,text2,label`):
  out/train_synth.csv  — within-API pairs among synthetic snippets only
  out/train_real.csv   — within-API pairs over real (KB + train-split GitHub)
                          only (the 'real-only' ablation, clean replacement for
                          the shipped vendors/SafeNet train.csv)
  out/train_mixed.csv  — within-API pairs over real (KB + train-split GitHub)
                          x real/synth (the 'train on synthetic + real' formula)
  out/train_hard.csv   — cross-API pairs, always label -1 (adversarial +
                          easy negatives; at least one side synthetic)

Real GitHub rows are restricted to splits/train.txt.  The valid and test
splits are never paired here, and the build refuses to write any CSV that
contains a holdout snippet (`splits/check_train_leakage.py` enforces the same
invariant independently).  Before 2026-11-18 this file walked all of
`testdata/`, which leaked every valid/test snippet into the training CSVs.

Label rule (matches converttrainset.py semantics, extended with the API): 1 iff
same (api, pattern_id), else -1. Rows are shuffled (seed 1234, the baseline
seed) and label-balanced 50/50.

Also processes the real corpora through the *same* extract_ast + preprocess
pipeline (cached under out/ast_json_real/) so both sides share one format.
"""

import json
import os
import random
import re
import sys

import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "pipe"))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "splits"))
from common import SYNTH_ROOT  # noqa: E402
from holdout import check_csvs, holdout_sequences, load_split  # noqa: E402
import preprocess  # noqa: E402
import syn_parser  # noqa: E402

REPO_SAFE = os.path.join(SYNTH_ROOT, "..", "..", "vendors", "SafeNet")
OUT_AST_REAL = os.path.join(SYNTH_ROOT, "out", "ast_real")
OUT_JSON_REAL = os.path.join(SYNTH_ROOT, "out", "ast_json_real")
OUT_MANIFEST = os.path.join(SYNTH_ROOT, "out", "pairs_manifest.jsonl")
SEED = 1234


def api_key(name):
    return name.replace("(c)", "").strip()


def pattern_of(filename):
    m = re.match(r"^(\d+)-", filename)
    return int(m.group(1)) if m else None


def process_real():
    """Extract + preprocess the KB and the train slice of testdata.

    The frozen split is read from `splits/train.txt`; files outside it are
    skipped before their sequence is cached or paired.
    """
    train_gh = set(load_split("train"))
    rows = []
    for corpus, root in (("kb", os.path.join(REPO_SAFE, "knowledgebase")),
                         ("gh", os.path.join(REPO_SAFE, "testdata"))):
        out_ast = os.path.join(OUT_AST_REAL, corpus)
        ok, failed = syn_parser.extract_tree(root, out_ast)
        print(f"real[{corpus}]: extract ok={ok} failed={failed}")
        for dirpath, _, files in os.walk(root):
            for fname in sorted(files):
                if not fname.endswith(".rs"):
                    continue
                rel_path = os.path.relpath(os.path.join(dirpath, fname), root)
                rel_path = rel_path.replace(os.sep, "/")
                if corpus == "gh" and rel_path not in train_gh:
                    continue
                rel_dir = os.path.dirname(rel_path)
                stem = fname[:-3]
                pattern = pattern_of(stem)
                if pattern is None:
                    continue
                ast_path = os.path.join(out_ast, rel_dir, stem + ".ast")
                if not os.path.isfile(ast_path):
                    continue
                json_path = os.path.join(OUT_JSON_REAL, corpus, rel_dir, stem + ".json")
                try:
                    seq = preprocess.ast_file_to_json(ast_path, json_path)
                except Exception as e:
                    print(f"real pipeline fail {corpus}/{rel_path}: {e}")
                    continue
                if not seq.split():
                    continue
                rows.append({
                    "api": api_key(rel_dir),
                    "pattern_id": pattern,
                    "kind": "safe" if "-safe" in stem else "unsafe",
                    "source": "real_" + corpus,
                    "rel_path": rel_path,
                    "text": seq,
                })
    return rows


def synth_rows():
    rows = []
    with open(OUT_MANIFEST, encoding="utf-8") as f:
        for line in f:
            rec = json.loads(line)
            if not rec.get("ok"):
                continue
            json_path = os.path.join(SYNTH_ROOT, "out", rec["ast_json"])
            with open(json_path, encoding="utf-8") as jf:
                seq = json.load(jf)
            rows.append({
                "api": api_key(rec["api"]),
                "pattern_id": rec["pattern_id"],
                "kind": rec["kind"],
                "source": rec["source"],
                "text": seq,
            })
    return rows


def balance(pos, neg, rng):
    rng.shuffle(pos)
    rng.shuffle(neg)
    n = min(len(pos), len(neg))
    return pos[:n] + neg[:n]


def pairs_within(rows, rng):
    """All unordered pairs within one API; label 1 iff same pattern."""
    by_api = {}
    for r in rows:
        by_api.setdefault(r["api"], []).append(r)
    pos, neg = [], []
    for _, items in sorted(by_api.items()):
        for i in range(len(items)):
            for j in range(i + 1, len(items)):
                a, b = items[i], items[j]
                (pos if a["pattern_id"] == b["pattern_id"] else neg).append(
                    (a["text"], b["text"],
                     1 if a["pattern_id"] == b["pattern_id"] else -1))
    return balance(pos, neg, rng)


def pairs_cross_api(rows, rng, half=500):
    """Cross-API negatives: same pattern id (adversarial) + random (easy)."""
    hard, easy = [], []
    for i in range(len(rows)):
        for j in range(i + 1, len(rows)):
            a, b = rows[i], rows[j]
            if a["api"] == b["api"]:
                continue
            if not (a["source"].startswith(("template", "counterfactual"))
                    or b["source"].startswith(("template", "counterfactual"))):
                continue
            (hard if a["pattern_id"] == b["pattern_id"] else easy).append(
                (a["text"], b["text"], -1))
    rng.shuffle(hard)
    rng.shuffle(easy)
    return hard[:half], easy[:half]


def write_csv(pairs, path):
    df = pd.DataFrame(pairs, columns=["text1", "text2", "label"])
    df = df.sample(frac=1, random_state=SEED).reset_index(drop=True)
    df.to_csv(path)  # index -> header matches the shipped ',text1,text2,label'
    return df


def drop_holdout_rows(rows, holdout, label):
    """Drop rows whose normalized sequence also occurs in valid/test.

    File membership is not sufficient: the corpus has cross-API identical
    sequences, so a train-split file can still carry a holdout sequence.  The
    frozen split's own audit reports these duplicate groups; this filter makes
    the training data sequence-disjoint from both holdouts.
    """
    texts = {seq for seqs in holdout.values() for seq in seqs.values()}
    kept, dropped = [], []
    for row in rows:
        (dropped if row["text"] in texts else kept).append(row)
    if dropped:
        print(f"{label}: dropped {len(dropped)} row(s) duplicating a holdout sequence")
        for row in dropped:
            where = row.get("rel_path") or row.get("source", "?")
            print(f"  {where} (source={row['source']})")
    return kept


def assert_no_holdout_leakage(named_pairs, names=("valid", "test"), holdout=None):
    """Fail before writing if any pair text comes from a holdout split.

    This is the in-memory half of the gate; `check_csvs` re-checks the written
    files so a future refactor cannot silently reintroduce the leak.
    """
    holdout = holdout or holdout_sequences(names)
    reverse = {name: {seq: rel for rel, seq in seqs.items()}
               for name, seqs in holdout.items()}
    failed = False
    for label, pairs in named_pairs.items():
        texts = set()
        for text1, text2, _ in pairs:
            texts.add(text1)
            texts.add(text2)
        parts, leaked = [], False
        for name, seqs in holdout.items():
            hits = texts & set(seqs.values())
            parts.append(f"{name}={len(hits)}/{len(seqs)}")
            leaked = leaked or bool(hits)
            if hits:
                failed = True
                for seq in sorted(hits)[:3]:
                    print(f"  {label} leaks {name}: {reverse[name][seq]}")
        print(f"{label}: {' '.join(parts)} -> {'LEAK' if leaked else 'OK'}")
    if failed:
        raise SystemExit(
            "refusing to write pair CSVs that contain valid/test snippets")


def main():
    rng = random.Random(SEED)
    holdout = holdout_sequences(("valid", "test"))
    real = drop_holdout_rows(process_real(), holdout, "real")
    synth = drop_holdout_rows(synth_rows(), holdout, "synth")
    n_kb = sum(1 for r in real if r["source"] == "real_kb")
    print(f"rows: real_kb={n_kb} real_gh_train={len(real) - n_kb} "
          f"synth_kept={len(synth)}")

    synth_pairs = pairs_within(synth, rng)
    real_pairs = pairs_within(real, rng)
    mixed_pairs = pairs_within(real + synth, rng)
    hard, easy = pairs_cross_api(synth + real, rng)
    assert_no_holdout_leakage({
        "train_synth": synth_pairs,
        "train_real": real_pairs,
        "train_mixed": mixed_pairs,
        "train_hard": hard + easy,
    }, holdout=holdout)

    d_synth = write_csv(synth_pairs,
                        os.path.join(SYNTH_ROOT, "out", "train_synth.csv"))
    d_real = write_csv(real_pairs,
                       os.path.join(SYNTH_ROOT, "out", "train_real.csv"))
    d_mixed = write_csv(mixed_pairs,
                        os.path.join(SYNTH_ROOT, "out", "train_mixed.csv"))
    d_hard = write_csv(hard + easy,
                       os.path.join(SYNTH_ROOT, "out", "train_hard.csv"))

    for name, df in (("train_synth", d_synth), ("train_real", d_real),
                     ("train_mixed", d_mixed), ("train_hard", d_hard)):
        vc = df["label"].value_counts().to_dict()
        lens = df["text1"].str.split().str.len()
        print(f"{name}: {len(df)} pairs labels={vc} "
              f"len_p50={int(lens.median())} max={int(lens.max())}")

    rc = check_csvs([os.path.join(SYNTH_ROOT, "out", name)
                     for name in ("train_synth.csv", "train_real.csv",
                                  "train_mixed.csv", "train_hard.csv")])
    if rc:
        raise SystemExit("written pair CSVs failed the holdout gate")


if __name__ == "__main__":
    main()
