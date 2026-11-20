"""Frozen-split lookup and the no-holdout-leakage gate.

The frozen protocol says valid/test snippets must never appear in a training
CSV.  `gen/pairs.py` used to walk all of `vendors/SafeNet/testdata/`, so the
mixed/hard CSVs contained every valid and test snippet, including 55 of the 76
test pairs verbatim.  This module is the single place that resolves split
membership and cached sequences so the pair builder, the eval builder, and the
standalone gate cannot disagree.

Usage as a gate (run before any training or evaluation):

    python splits/check_train_leakage.py
    python splits/check_train_leakage.py out/train_mixed.csv out/train_hard.csv
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import sys

SYNTH_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SPLITS_DIR = os.path.join(SYNTH_ROOT, "splits")
GH_CACHE = os.path.join(SYNTH_ROOT, "out", "ast_json_real", "gh")
SPLITS = ("train", "valid", "test")
DEFAULT_CSVS = tuple(os.path.join(SYNTH_ROOT, "out", f"train_{n}.csv")
                     for n in ("synth", "real", "mixed", "hard"))


def load_split(name: str) -> list[str]:
    """Read one frozen split file; fail loudly if the freeze is missing."""
    if name not in SPLITS:
        raise ValueError(f"unknown split {name!r}; expected one of {SPLITS}")
    path = os.path.join(SPLITS_DIR, f"{name}.txt")
    if not os.path.isfile(path):
        raise SystemExit(
            f"missing {path}; run `python splits/make_splits.py` first")
    with open(path, encoding="utf-8") as f:
        return [line.strip() for line in f if line.strip()]


def sequence_path(rel_path: str) -> str:
    """testdata-relative `.rs` path -> cached baseline sequence JSON."""
    stem = rel_path[:-3] if rel_path.endswith(".rs") else rel_path
    return os.path.join(GH_CACHE, *stem.split("/")) + ".json"


def load_sequences(name: str) -> dict[str, str]:
    """rel_path -> cached sequence for a split; fail if any cache is missing."""
    seqs, missing = {}, []
    for rel in load_split(name):
        path = sequence_path(rel)
        if not os.path.isfile(path):
            missing.append(rel)
            continue
        with open(path, encoding="utf-8") as f:
            seqs[rel] = json.load(f)
    if missing:
        sample = ", ".join(missing[:3])
        raise SystemExit(
            f"{name}.txt references {len(missing)} snippet(s) without a cached "
            f"sequence (e.g. {sample}); run the real-corpus preprocessing first")
    return seqs


def holdout_sequences(names: tuple[str, ...] = ("valid", "test")) -> dict[str, dict[str, str]]:
    return {name: load_sequences(name) for name in names}


def read_csv_texts(path: str) -> set[str]:
    """Every text1/text2 value in a pair CSV."""
    if not os.path.isfile(path):
        raise SystemExit(f"missing pair CSV: {path}")
    texts = set()
    with open(path, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        if not reader.fieldnames or not {"text1", "text2"} <= set(reader.fieldnames):
            raise SystemExit(f"{path}: need text1 and text2 columns")
        for row in reader:
            for key in ("text1", "text2"):
                text = row.get(key) or ""
                if text:
                    texts.add(text)
    return texts


def leakage_report(path: str, holdout: dict[str, dict[str, str]]) -> dict[str, set[str]]:
    """split name -> set of holdout rel_paths whose sequence is in `path`."""
    texts = read_csv_texts(path)
    found = {}
    for name, seqs in holdout.items():
        found[name] = {rel for rel, seq in seqs.items() if seq in texts}
    return found


def check_csvs(paths: list[str], names: tuple[str, ...] = ("valid", "test"),
               verbose: bool = True) -> int:
    """Return 0 if every CSV is holdout-clean, 1 otherwise."""
    holdout = holdout_sequences(names)
    failed = False
    for path in paths:
        found = leakage_report(path, holdout)
        parts = [f"{name}={len(hits)}/{len(holdout[name])}"
                 for name, hits in found.items()]
        bad = any(found.values())
        if verbose:
            label = os.path.relpath(path, SYNTH_ROOT)
            print(f"{label}: {' '.join(parts)} -> {'LEAK' if bad else 'OK'}")
            for name, hits in found.items():
                for rel in sorted(hits)[:3]:
                    print(f"  {name} leak: {rel}")
        failed = failed or bad
    return 1 if failed else 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description="Fail if a pair-training CSV contains a valid/test snippet.")
    ap.add_argument("csv", nargs="*", default=list(DEFAULT_CSVS),
                    help="pair CSVs to check (default: out/train_{synth,real,mixed,hard}.csv)")
    ap.add_argument("--split", action="append", choices=("valid", "test"),
                    help="holdout split to check (repeatable; default: both)")
    args = ap.parse_args(argv)
    names = tuple(args.split) if args.split else ("valid", "test")
    return check_csvs(args.csv, names)


if __name__ == "__main__":
    raise SystemExit(main())
