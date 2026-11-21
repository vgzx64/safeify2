"""Frozen ModernBERT-base embeddings for the transition core (v0.2).

Encodes `old_snippet` for train + valid rows only; `test` stays sealed (not
encoded). Output: out/modernbert_base_v0.2.npz with mean-pooled, L2-normalised
embeddings plus the row metadata needed by baseline_embeddings.py.

Usage: cd safeify-data/transitions && python embed_modernbert.py
"""

from __future__ import annotations

import json
import time
from pathlib import Path

import numpy as np
import torch
from transformers import AutoModel, AutoTokenizer

OUT = Path(__file__).resolve().parent / "out"
CORE = OUT / "transitions_core_v0.2.jsonl"
NPZ = OUT / "modernbert_base_v0.2.npz"
MODEL = "answerdotai/ModernBERT-base"
MAX_LEN = 256
BATCH = 16


def main():
    rows = [json.loads(line) for line in open(CORE, encoding="utf-8") if line.strip()]
    rows = [r for r in rows if r["split"] in ("train", "valid")]  # test sealed
    texts = [r["old_snippet"] for r in rows]

    torch.set_num_threads(12)
    tok = AutoTokenizer.from_pretrained(MODEL)
    model = AutoModel.from_pretrained(MODEL).eval()

    lens = [len(tok(t)["input_ids"]) for t in texts]
    order = np.argsort(lens)  # length-sorted batches keep CPU padding cheap
    emb = np.zeros((len(texts), model.config.hidden_size), dtype=np.float32)
    done = 0
    t0 = time.time()
    with torch.inference_mode():
        for start in range(0, len(order), BATCH):
            idx = order[start:start + BATCH]
            enc = tok([texts[i] for i in idx], padding=True, truncation=True,
                      max_length=MAX_LEN, return_tensors="pt")
            hidden = model(**enc).last_hidden_state
            mask = enc["attention_mask"].unsqueeze(-1).float()
            pooled = (hidden * mask).sum(dim=1) / mask.sum(dim=1)
            pooled = torch.nn.functional.normalize(pooled, dim=-1)
            emb[idx] = pooled.numpy()
            done += len(idx)
            if start % (BATCH * 10) == 0:
                rate = sum(min(l, MAX_LEN) for l in np.asarray(lens)[order[:done]]) / max(1e-9, time.time() - t0)
                print(f"encoded {done}/{len(texts)} ({time.time() - t0:.0f}s, {rate:.0f} tok/s)", flush=True)

    np.savez_compressed(
        NPZ, emb=emb,
        y=np.array([r["target"] for r in rows], dtype=np.int64),
        split=np.array([r["split"] for r in rows]),
        repo=np.array([r["repo_key"] for r in rows]),
        ids=np.array([r["id"] for r in rows]),
        tokens=np.array(lens, dtype=np.int64),
    )
    print(f"wrote {NPZ} shape={emb.shape} in {time.time() - t0:.0f}s; "
          f"tokens p50={int(np.median(lens))} max={int(max(lens))}")


if __name__ == "__main__":
    main()
