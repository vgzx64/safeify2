# splits/ — frozen real held-out split (testdata queries)

Regenerate: `python splits/make_splits.py` (from `research/synth/`);
verify an untouched checkout: `python splits/make_splits.py --check`.

## What is split, and what is not

| corpus | role | split? |
|---|---|---|
| `vendors/SafeNet/knowledgebase/` (142 .rs) | retrieval **gallery** (fixed) | no — never a query |
| `vendors/SafeNet/testdata/` (474 .rs) | real **queries** | yes — 70/10/20 |
| `research/synth/out/snippets/` | synthetic training rows | no — never evaluated |

* stratified by **(api, pattern_id)**, seed 1234, per-file stable
  seed (no global RNG) → byte-identical on re-run.
* only **usable** files get a split: a pattern id in the filename AND a cached
  sequence in `out/ast_json_real/gh/` (survived `extract_ast` + baseline
  preprocess). 454 usable / 474 total,
  20 excluded:

- `Box::from_raw/1-9.rs` — no_cached_sequence
- `CStr::from_ptr/1-1 .rs` — no_cached_sequence
- `CStr::from_ptr/1-5.rs` — no_cached_sequence
- `Rc::from_raw/pending.rs` — no_pattern_id
- `Vec::from_raw_parts/2-1.rs` — no_cached_sequence
- `assume_init /1-13.rs` — no_cached_sequence
- `assume_init /3-4.rs` — no_cached_sequence
- `mem::zeroed/1-2.rs` — no_cached_sequence
- `offset_from/5-1.rs` — no_cached_sequence
- `ptr::copy_nonoverlapping/3-5.rs` — no_cached_sequence
- `ptr::deref/1-3.rs` — no_cached_sequence
- `ptr::write/4-10.rs` — no_cached_sequence
- `ptr::write/4-14.rs` — no_cached_sequence
- `ptr::write_bytes/2-1.rs` — no_cached_sequence
- `ptr::write_bytes/5-2.rs` — no_cached_sequence
- `set_len/1-12.rs` — no_cached_sequence
- `set_len/1-5.rs` — no_cached_sequence
- `set_len/2-6.rs` — no_cached_sequence
- `set_len/2-9.rs` — no_cached_sequence
- `set_len/3-6.rs` — no_cached_sequence

## Sizes

| split | usable .rs | pairs | target |
|---|---|---|---|
| train | 288 | — | 70% |
| valid | 69 | 10 (5 pos / 5 neg) | 10% |
| test  | 97 | 76 (38 pos / 38 neg) | 20% |

## Training-data integrity

The pair CSVs are built from `train.txt` + the KB only. File membership is not
enough because the corpus has cross-API identical sequences: six train-split
files carry a sequence that also occurs in valid/test, so `gen/pairs.py` drops
them before pairing. Before any training run:

```bash
python splits/check_train_leakage.py
# out/train_synth.csv: valid=0/69 test=0/97 -> OK
# out/train_real.csv:  valid=0/69 test=0/97 -> OK
# out/train_mixed.csv: valid=0/69 test=0/97 -> OK
# out/train_hard.csv:  valid=0/69 test=0/97 -> OK
```

The shipped `vendors/SafeNet/src/model/data/baaaa/train.csv` is **not** clean:
it contains 25 test and 23 valid snippets. Use the rebuilt `train_real.csv`
for the real-only ablation and never train on the shipped CSV for a held-out
claim.

## Leakage audit (exact sequence sha256 across splits)

* same-API overlap (real leakage): **0**
* cross-API identical sequences (informational): 6
* duplicate groups with conflicting gold pattern ids: 14
  (corpus defect, e.g. `ptr::copy/4-13.rs` is byte-identical to
  `ptr::copy/1-2(4-14).rs` — same sequence, two filenames, two pattern ids).
  These groups are kept together in ONE split (never split across), and every
  conflict is itemised in `stats.json → label_conflicts` for manual review.

## Per-stratum counts

| api | pattern | train | valid | test | total |
|---|---|---|---|---|---|
| Box::from_raw | 1 | 9 | 1 | 2 | 12 |
| Box::from_raw | 2 | 1 | 0 | 1 | 2 |
| Box::from_raw | 3 | 3 | 1 | 1 | 5 |
| Box::from_raw | 4 | 1 | 1 | 1 | 3 |
| Box::from_raw | 5 | 1 | 0 | 0 | 1 |
| CStr::from_ptr | 1 | 11 | 1 | 2 | 14 |
| CStr::from_ptr | 2 | 1 | 0 | 0 | 1 |
| CStr::from_ptr | 3 | 5 | 1 | 1 | 7 |
| CStr::from_ptr | 4 | 1 | 0 | 0 | 1 |
| CString::from_raw | 1 | 5 | 1 | 1 | 7 |
| CString::from_raw | 2 | 1 | 1 | 1 | 3 |
| CString::from_raw | 3 | 2 | 1 | 1 | 4 |
| CString::from_raw | 4 | 5 | 1 | 1 | 7 |
| Rc::from_raw | 1 | 7 | 1 | 2 | 10 |
| Rc::from_raw | 2 | 1 | 1 | 1 | 3 |
| Rc::from_raw | 3 | 1 | 0 | 1 | 2 |
| Rc::from_raw | 4 | 3 | 1 | 1 | 5 |
| Vec::from_raw_parts | 1 | 2 | 1 | 1 | 4 |
| Vec::from_raw_parts | 2 | 3 | 1 | 1 | 5 |
| Vec::from_raw_parts | 3 | 6 | 1 | 2 | 9 |
| Vec::from_raw_parts | 4 | 1 | 1 | 1 | 3 |
| Vec::from_raw_parts | 5 | 2 | 1 | 2 | 5 |
| as_ref | 1 | 4 | 1 | 1 | 6 |
| as_ref | 2 | 4 | 1 | 1 | 6 |
| as_ref | 3 | 5 | 1 | 1 | 7 |
| as_ref | 4 | 1 | 0 | 0 | 1 |
| assume_init | 1 | 11 | 2 | 3 | 16 |
| assume_init | 2 | 1 | 0 | 0 | 1 |
| assume_init | 3 | 2 | 1 | 1 | 4 |
| assume_init | 4 | 1 | 1 | 1 | 3 |
| mem::transmute | 1 | 11 | 1 | 3 | 15 |
| mem::transmute | 2 | 7 | 1 | 2 | 10 |
| mem::transmute | 3 | 1 | 0 | 1 | 2 |
| mem::transmute | 6 | 1 | 1 | 1 | 3 |
| mem::transmute_copy | 1 | 3 | 1 | 1 | 5 |
| mem::transmute_copy | 2 | 2 | 1 | 1 | 4 |
| mem::transmute_copy | 3 | 1 | 0 | 0 | 1 |
| mem::transmute_copy | 4 | 4 | 1 | 1 | 6 |
| mem::transmute_copy | 6 | 4 | 1 | 1 | 6 |
| mem::zeroed | 1 | 5 | 1 | 1 | 7 |
| mem::zeroed | 2 | 2 | 1 | 1 | 4 |
| offset_from | 1 | 3 | 1 | 1 | 5 |
| offset_from | 2 | 1 | 0 | 0 | 1 |
| offset_from | 3 | 8 | 1 | 2 | 11 |
| offset_from | 4 | 6 | 1 | 2 | 9 |
| offset_from | 5 | 1 | 1 | 1 | 3 |
| ptr::copy | 1 | 3 | 2 | 1 | 6 |
| ptr::copy | 2 | 2 | 1 | 1 | 4 |
| ptr::copy | 3 | 2 | 1 | 1 | 4 |
| ptr::copy | 4 | 8 | 2 | 3 | 13 |
| ptr::copy | 5 | 3 | 0 | 1 | 4 |
| ptr::copy_nonoverlapping | 1 | 1 | 1 | 1 | 3 |
| ptr::copy_nonoverlapping | 2 | 1 | 1 | 1 | 3 |
| ptr::copy_nonoverlapping | 3 | 6 | 1 | 1 | 8 |
| ptr::copy_nonoverlapping | 4 | 8 | 2 | 2 | 12 |
| ptr::copy_nonoverlapping | 5 | 1 | 1 | 3 | 5 |
| ptr::deref | 1 | 5 | 1 | 2 | 8 |
| ptr::deref | 2 | 3 | 1 | 1 | 5 |
| ptr::deref | 3 | 6 | 1 | 2 | 9 |
| ptr::deref | 4 | 7 | 1 | 2 | 10 |
| ptr::read | 1 | 4 | 1 | 1 | 6 |
| ptr::read | 2 | 4 | 1 | 1 | 6 |
| ptr::read | 4 | 10 | 1 | 4 | 15 |
| ptr::read | 5 | 1 | 1 | 1 | 3 |
| ptr::write | 1 | 4 | 1 | 1 | 6 |
| ptr::write | 2 | 2 | 1 | 1 | 4 |
| ptr::write | 3 | 1 | 0 | 0 | 1 |
| ptr::write | 4 | 8 | 1 | 3 | 12 |
| ptr::write | 5 | 2 | 1 | 1 | 4 |
| ptr::write_bytes | 1 | 1 | 1 | 1 | 3 |
| ptr::write_bytes | 2 | 2 | 1 | 1 | 4 |
| ptr::write_bytes | 4 | 10 | 2 | 3 | 15 |
| ptr::write_bytes | 5 | 1 | 1 | 1 | 3 |
| set_len | 1 | 8 | 1 | 2 | 11 |
| set_len | 2 | 7 | 1 | 2 | 10 |
| set_len | 3 | 6 | 1 | 1 | 8 |

## Evaluation protocol (enforced by `splits/eval_protocol.py`)

1. **Train** on `out/train_real.csv`, `out/train_synth.csv`, or
   `out/train_mixed.csv` (+`out/train_hard.csv`). All four must pass
   `splits/check_train_leakage.py`; do not use the shipped SafeNet `train.csv`.
2. **Select** epochs/threshold on `valid` only:
   `python splits/make_eval.py --split valid`, then
   `python splits/eval_protocol.py --split valid --pairs-preds <preds.csv>`.
   The valid set is only 10 pairs (5 pos / 5 neg) and has no both-N pairs, so
   it is a weak selection signal; prefer grouped CV on train and report the
   limitation.
3. **Report once** on `test`:
   `python splits/make_eval.py --split test`, then
   `python splits/eval_protocol.py --split test --pairs-preds <preds.csv>`.
   Pair metrics + per-pattern recall + FP rate on `verdict=N`; the test pair
   set has 38 pos / 38 neg and only 3 both-N pairs, so the safety FP estimate
   is coarse.
4. Never report a synthetic-measured number as a result
   (`notes/research/synthetic-data-theory.md`).

Gold verdicts per (api, pattern) live in `kb_verdicts.json`, transcribed from
`vendors/SafeNet/knowledgebase/README.md`.

The pair-model plan and current blockers are in
[notes/research/bert-pair-model.md](../../../notes/research/bert-pair-model.md).
