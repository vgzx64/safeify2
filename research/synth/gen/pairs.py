"""Build BERT/SNN training pair CSVs (baseline-identical format).

Outputs (all with the shipped header `,text1,text2,label`):
  out/train_synth.csv  — within-API pairs among synthetic snippets only
  out/train_mixed.csv  — within-API pairs over real (KB+GitHub) x real/synth
                          (the 'train on synthetic + real' formula)
  out/train_hard.csv   — cross-API pairs, always label -1 (adversarial +
                          easy negatives; at least one side synthetic)

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
from common import SYNTH_ROOT  # noqa: E402
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
    """Extract + preprocess KB and testdata; returns row dicts."""
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
                rel_dir = os.path.relpath(dirpath, root)
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
                    print(f"real pipeline fail {corpus}/{rel_dir}/{fname}: {e}")
                    continue
                if not seq.split():
                    continue
                rows.append({
                    "api": api_key(rel_dir),
                    "pattern_id": pattern,
                    "kind": "safe" if "-safe" in stem else "unsafe",
                    "source": "real_" + corpus,
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


def main():
    rng = random.Random(SEED)
    real = process_real()
    synth = synth_rows()
    print(f"rows: real={len(real)} synth_kept={len(synth)}")

    d_synth = write_csv(pairs_within(synth, rng),
                        os.path.join(SYNTH_ROOT, "out", "train_synth.csv"))
    d_mixed = write_csv(pairs_within(real + synth, rng),
                        os.path.join(SYNTH_ROOT, "out", "train_mixed.csv"))
    hard, easy = pairs_cross_api(synth + real, rng)
    d_hard = write_csv(hard + easy, os.path.join(SYNTH_ROOT, "out", "train_hard.csv"))

    for name, df in (("train_synth", d_synth), ("train_mixed", d_mixed),
                     ("train_hard", d_hard)):
        vc = df["label"].value_counts().to_dict()
        lens = df["text1"].str.split().str.len()
        print(f"{name}: {len(df)} pairs labels={vc} "
              f"len_p50={int(lens.median())} max={int(lens.max())}")


if __name__ == "__main__":
    main()
