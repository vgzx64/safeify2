"""Format-compatibility validation: generated CSVs vs the shipped train.csv."""

import os
import sys

import pandas as pd

SYNTH_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BASELINE = os.path.join(SYNTH_ROOT, "..", "..", "vendors", "SafeNet",
                        "src", "model", "data", "baaaa", "train.csv")


def main():
    base = pd.read_csv(BASELINE)
    base_vocab = set()
    for col in ("text1", "text2"):
        for text in base[col]:
            base_vocab.update(str(text).split())
    failures = []

    with open(BASELINE, encoding="utf-8") as f:
        base_header = f.readline().rstrip("\n")

    for name in ("train_synth", "train_mixed", "train_hard"):
        path = os.path.join(SYNTH_ROOT, "out", f"{name}.csv")
        with open(path, encoding="utf-8") as f:
            header = f.readline().rstrip("\n")
        if header != base_header:
            failures.append(f"{name}: header {header!r} != baseline {base_header!r}")
        df = pd.read_csv(path)
        if list(df.columns) != ["Unnamed: 0", "text1", "text2", "label"]:
            failures.append(f"{name}: columns {list(df.columns)}")
        if not set(df["label"].unique()) <= {1, -1}:
            failures.append(f"{name}: labels {df['label'].unique()}")
        for col in ("text1", "text2"):
            if df[col].isna().any() or (df[col].str.len() == 0).any():
                failures.append(f"{name}: empty {col}")
            # informational: token vocabulary relative to the shipped baseline.
            # Legit expansions exist: wider corpus (async/Pin/dot2 in real GH
            # files), wrapper mod_token, and the baseline's own str.replace
            # rename-collision artifacts (cf. var7llocator in train.csv).
            off = {t for text in df[col] for t in text.split()
                   if t not in base_vocab}
            if off:
                print(f"  info {name}: {len(off)} token types unseen in baseline "
                      f"(e.g. {sorted(off)[:6]})")
        # row access exactly like preprocess/processor.py (iloc)
        row = df.iloc[0]
        _ = row["text1"], row["text2"], row["label"]
        print(f"{name}: OK  ({len(df)} pairs, header identical)")

    if failures:
        print("\nFAILURES:")
        for x in failures:
            print(" -", x)
        sys.exit(1)
    print("format validation passed")


if __name__ == "__main__":
    main()
