# BERT pair model (NIRM 4) — status and first plan

> **Status: planned · 2026-11-18 · no model trained**
>
> Scope: the SafeNet-style **pair classifier** for NIRM 4. This is not part of
> NIRM 3. The NIRM 3 detector is documented in
> [nirm3/report.md](../nirm3/report.md).
>
> Data: [`research/synth`](../../research/synth/README.md), frozen split
> [`research/synth/splits`](../../research/synth/splits/README.md).

## Current state

The data prerequisite is now met; the model prerequisite is not.

**Ready**

- Pair-training CSVs are built from the frozen train split + KB only. The
  2026-11-18 rebuild removed every valid/test snippet, including six train-split
  files whose normalized sequence duplicated a holdout sequence.
- Current sizes: `train_synth` 2,628 · `train_real` 2,688 · `train_mixed` 8,580 ·
  `train_hard` 1,000 pairs.
- `python splits/check_train_leakage.py` prints `OK` for all four files
  (0/69 valid, 0/97 test). The exact test pair overlap is 0.
- A valid selection path exists: `valid_pairs.csv` (10 pairs: 5 pos / 5 neg)
  and `eval_protocol.py --split valid`. Test stays sealed at 76 pairs.
- The shipped `vendors/SafeNet/.../train.csv` is **not** clean (25 test, 23
  valid snippets); `train_real.csv` replaces it for the real-only ablation.

**Not ready**

- No BERT checkpoint or tokenizer recipe is pinned. SafeNet's custom
  `bert_wwm_mlm` checkpoint is absent; `src/model/data/pretrained/` is empty.
- The vendor training entry point does not run as-is: `train.sh` references a
  missing `main.py`, and the code uses `transformers.AdamW` and
  `pad_to_max_length`, both removed in the installed `transformers` 5.x.
- No GPU. A synthetic BERT-base forward measured ~62.7 s at batch 16 × 100
  tokens on this machine; the vendor per-pair, per-epoch recipe is not usable.
- The valid pair set is only 10 pairs and has no both-N pairs, so it cannot
  select a threshold reliably or estimate the safety FP rate.
- No model has been trained; there is no accuracy to report.

## Chosen first approach: frozen-BERT embedding cache + pair head

This is the smallest CPU-feasible baseline, not the final model.

1. **BERT is frozen.** Lock its weights; use it only to turn a snippet into a
   vector (an embedding).
2. **Embedding cache.** Run BERT once on every *unique* training snippet and
   save `{snippet: vector}` to disk. The 8,580 pairs come from only **715
   unique snippets** (394 real + 321 synthetic), so BERT runs 715 times total
   instead of once per pair per epoch.
3. **Pair head.** Train a small comparator (a cosine score with a learned
   scale, or a one/two-layer MLP) on two cached vectors. It has a few thousand
   parameters, so it trains in minutes on CPU.

```
offline:  unique snippet -> frozen BERT -> vector -> cache
train:    pair -> load two vectors -> pair head -> same-pattern score
inference: new snippet -> BERT once -> compare with gallery/cached vectors
```

Why this first:

- It makes the experiment feasible on CPU and allows fast ablations
  (real-only / synthetic / mixed / +hard negatives).
- It gives a clean baseline before any GPU fine-tuning decision.
- It is mathematically equivalent to training the head on frozen BERT outputs.

What it does **not** solve:

- BERT never adapts to Rust unsafe patterns, so accuracy has a ceiling.
- The checkpoint/tokenizer decision still has to be made; a generic
  `bert-base-uncased` tokenizer may tokenize the AST token sequences poorly.
- Inference still needs BERT for new snippets.
- Changing the checkpoint, tokenizer, max length, or unfreezing BERT invalidates
  the cache.
- The 10-pair valid set remains weak; use grouped CV on train and treat valid as
  a sanity check.

## Open decisions

1. **Checkpoint/tokenizer.** Options: `bert-base-uncased`, CodeBERT, or
   reproduce SafeNet's MLM pretraining on the AST token sequences. Pick one and
   record it before training.
2. **Input text.** Keep the shipped preorder AST-token sequence; do not silently
   switch to raw Rust, or the comparison with SafeNet is lost.
3. **Head and loss.** Start with cosine similarity plus a learned scale and a
   binary/contrastive loss; only add an MLP if the baseline underfits.
4. **Selection.** Grouped CV on `train` (groups = source file/API) plus the
   10-pair valid check. Score `test` once.
5. **Acceptance criteria.** Pair macro-F1, per-pattern recall, and FP rate on
   both-N pairs, against a TF-IDF or constant baseline; report intervals and
   sample sizes.

## Execution gates

1. `make_splits.py --check` → `OK`; `check_train_leakage.py` → `OK`.
2. Cache embeddings with `model.eval()`, no dropout, fixed tokenizer/max length;
   verify the cache is deterministic.
3. Train only the head; select on grouped CV / valid; keep test sealed.
4. Score test once with `eval_protocol.py --split test`; write the result and
   limitations into this note.
5. If unfreezing BERT is attempted later, invalidate the cache and record the
   GPU/time budget first.

## Related documents

- [Transition dataset plan](transition-dataset.md)
- [Pilot results](transition-dataset-pilot.md)
- [Synthetic data and frozen split](../../research/synth/README.md)
- [SafeNet frozen split protocol](../../research/synth/splits/README.md)
- [NIRM 3 report §11 — NIRM 4 handoff](../nirm3/report.md#11-nirm-4-handoff-bert-pair-model-data-readiness)
- [GNN-Coder evaluation](gnn-coder-evaluation.md) — a later augmentation, not the
  first baseline
