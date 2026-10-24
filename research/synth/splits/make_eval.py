"""Build evaluation artifacts from the frozen split (run AFTER make_splits.py).

Outputs (under splits/):
  gallery.json   fixed KB gallery: per-api list of {id, pattern_id, kind,
                 text} — what a query retrieves against. Never split.
  test_pairs.csv shipped-format pairs over held-out test snippets ONLY
                 (`,text1,text2,label`; label 1 iff same (api, pattern),
                 balanced 50/50, shuffled seed 1234 — same rules as
                 gen/pairs.py so the CSV loads in SentencePairDataset as-is).
  eval_manifest.json  per-row provenance for test_pairs.csv (api/pattern/
                 verdict of both endpoints) + gallery ids + hash of the
                 frozen split files (proves which split was evaluated).

Both sequences come from the SAME cached pipeline (out/ast_json_real/{gh,kb})
used to build train CSVs — format-faithful by construction.

Usage:  python splits/make_eval.py     (from research/synth/)
"""

import csv
import hashlib
import json
import os
import random
import sys

SYNTH_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SAFE_ROOT = os.path.join(SYNTH_ROOT, "..", "..", "vendors", "SafeNet")
KB = os.path.join(SAFE_ROOT, "knowledgebase")
KB_CACHE = os.path.join(SYNTH_ROOT, "out", "ast_json_real", "kb")
GH_CACHE = os.path.join(SYNTH_ROOT, "out", "ast_json_real", "gh")
SPLITS_DIR = os.path.join(SYNTH_ROOT, "splits")
SEED = 1234

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from make_splits import api_key, pattern_of  # noqa: E402  (shared helpers)


def load_verdicts():
    with open(os.path.join(SPLITS_DIR, "kb_verdicts.json"),
              encoding="utf-8") as f:
        return json.load(f)["apis"]


def verdict_of(verdicts, api, pattern_id):
    return verdicts.get(api, {}).get(str(pattern_id))


def load_gallery(verdicts):
    """Fixed KB gallery: every cached kb sequence, grouped by api."""
    gallery = {}
    missing = []
    for dirpath, _, files in os.walk(KB):
        for fname in sorted(files):
            if not fname.endswith(".rs"):
                continue
            pattern = pattern_of(fname)
            if pattern is None:
                continue
            api = api_key(os.path.relpath(dirpath, KB))
            rel = os.path.relpath(os.path.join(dirpath, fname), KB)
            json_path = os.path.join(KB_CACHE, *rel.split(os.sep))[:-3] + ".json"
            if not os.path.isfile(json_path):
                missing.append(rel.replace(os.sep, "/"))
                continue
            with open(json_path, encoding="utf-8") as f:
                seq = json.load(f)
            if not seq.split():
                continue
            gallery.setdefault(api, []).append({
                "id": f"{api}/{fname[:-3]}",
                "pattern_id": pattern,
                "kind": "safe" if "-safe" in fname[:-3] else "unsafe",
                "verdict": verdict_of(verdicts, api, pattern),
                "text": seq,
            })
    for api in gallery:
        gallery[api].sort(key=lambda g: (g["pattern_id"], g["id"]))
    return gallery, missing


def load_split_rows(split, verdicts):
    """Held-out test snippets for one split (from the frozen manifest)."""
    with open(os.path.join(SPLITS_DIR, "manifest.json"), encoding="utf-8") as f:
        manifest = json.load(f)
    rows = []
    for rec in manifest["files"]:
        if rec.get("split") != split:
            continue
        json_path = os.path.join(GH_CACHE,
                                 *rec["rel_path"].split("/"))[:-3] + ".json"
        with open(json_path, encoding="utf-8") as f:
            seq = json.load(f)
        rows.append({
            "rel_path": rec["rel_path"],
            "api": rec["api"],
            "pattern_id": rec["pattern_id"],
            "kind": rec["kind"],
            "verdict": verdict_of(verdicts, rec["api"], rec["pattern_id"]),
            "text": seq,
        })
    return rows


def make_pairs(rows, rng):
    """Within-API pairs; label 1 iff same (api, pattern). Balanced 50/50."""
    by_api = {}
    for r in rows:
        by_api.setdefault(r["api"], []).append(r)
    pos, neg = [], []
    for api in sorted(by_api):
        items = by_api[api]
        for i in range(len(items)):
            for j in range(i + 1, len(items)):
                a, b = items[i], items[j]
                same = a["pattern_id"] == b["pattern_id"]
                (pos if same else neg).append((a, b, 1 if same else -1))
    rng.shuffle(pos)
    rng.shuffle(neg)
    n = min(len(pos), len(neg))
    pairs = pos[:n] + neg[:n]
    rng.shuffle(pairs)
    return pairs


def write_pairs_csv(pairs, path):
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["", "text1", "text2", "label"])
        for i, (a, b, label) in enumerate(pairs):
            w.writerow([i, a["text"], b["text"], label])


def sha_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        h.update(f.read())
    return h.hexdigest()


def main():
    verdicts = load_verdicts()
    gallery, gal_missing = load_gallery(verdicts)
    split_name = "test"
    rows = load_split_rows(split_name, verdicts)
    if not rows:
        raise SystemExit("no rows in split — run make_splits.py first")
    pairs = make_pairs(rows, random.Random(SEED))

    with open(os.path.join(SPLITS_DIR, "gallery.json"), "w",
              encoding="utf-8") as f:
        json.dump({"source": "vendors/SafeNet/knowledgebase",
                   "apis": gallery}, f, ensure_ascii=False)

    csv_path = os.path.join(SPLITS_DIR, f"{split_name}_pairs.csv")
    write_pairs_csv(pairs, csv_path)

    manifest = {
        "split": split_name,
        "seed": SEED,
        "n_snippets": len(rows),
        "n_pairs": len(pairs),
        "n_pos": sum(1 for *_, l in pairs if l == 1),
        "n_neg": sum(1 for *_, l in pairs if l == -1),
        "gallery_apis": len(gallery),
        "gallery_entries": sum(len(v) for v in gallery.values()),
        "gallery_missing_cache": gal_missing,
        "split_file_sha256": {s: sha_file(os.path.join(SPLITS_DIR,
                                                       f"{s}.txt"))
                              for s in ("train", "valid", "test")},
        "rows": [{"rel_path": r["rel_path"], "api": r["api"],
                  "pattern_id": r["pattern_id"], "verdict": r["verdict"]}
                 for r in rows],
        "pairs": [{"i": i, "api": a["api"], "p1": a["pattern_id"],
                   "p2": b["pattern_id"],
                   "v1": a["verdict"], "v2": b["verdict"], "label": l}
                  for i, (a, b, l) in enumerate(pairs)],
    }
    with open(os.path.join(SPLITS_DIR, "eval_manifest.json"), "w",
              encoding="utf-8") as f:
        json.dump(manifest, f, ensure_ascii=False)

    print(f"eval: {split_name} snippets={len(rows)} pairs={len(pairs)} "
          f"(pos={manifest['n_pos']} neg={manifest['n_neg']}) "
          f"gallery={manifest['gallery_entries']} entries / "
          f"{len(gallery)} apis")
    if gal_missing:
        print(f"WARN gallery entries without cached sequence: {gal_missing}")


if __name__ == "__main__":
    main()
