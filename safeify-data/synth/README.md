# safeify-data/synth — deterministic synthetic dataset

> **Status: data ready · Updated: 2026-11-18 · no model trained**
>
> Training data is leakage-gated against valid/test. The pair-model plan and
> remaining blockers are in
> [notes/research/bert-pair-model.md](../../notes/research/bert-pair-model.md).

Implements strategies **A (counterfactual injection)** and **B (template/rule
generation)** from `notes/research/synthetic-data-theory.md`. No LLM is used:
everything is deterministic, rustc-verified, and re-runnable on consumer
hardware (per `notes/research/research-vectors.md`).

```
safe → unsafe by a known inverse transform ⇒ the safe original IS the ground-truth replacement
```

## Quickstart

```bash
cd safeify-data/synth
python build.py                   # generate -> verify -> pair -> report
python verify/validate_format.py  # format gate vs shipped train.csv
python splits/make_splits.py      # FREEZE the real held-out split (idempotent)
python splits/make_splits.py --check   # verify the freeze didn't drift
python splits/make_eval.py --split valid  # selection pairs (valid only)
python splits/make_eval.py --split test   # report-once pairs (test only)
python splits/check_train_leakage.py      # all training CSVs must print OK
python splits/eval_protocol.py            # audit: sizes, leakage, verdict coverage
```

Requires: `rustc`, cargo-built `tools/extract_ast` (`cargo build --release`
inside it), Python with `pandas` + `pyyaml` (repo venv).

## Layout

```
rules/*.yaml            42 rule cells (strategy B): api, pattern_id, replaceability,
                        verdict, contract, grid, unsafe[/safe][/encap] templates
seeds/safe/*.rs         5 safe seed templates (strategy A inputs)
gen/template.py         renders rules -> snippets + records
gen/inject.py           renders seeds and applies inverse-transform injections
gen/derive_contexts.py  re-emits every snippet inside `mod synth_m1 {..}` / nested,
                        because type/name-only variants collapse under the baseline
                        normalization (see Findings)
gen/pairs.py            processes the REAL corpora through the same pipeline and
                        writes train_synth.csv / train_mixed.csv / train_hard.csv
pipe/preprocess.py      importable port of SafeNet simplifyast.py + addnumtree.py
pipe/syn_parser.py      wrapper for tools/extract_ast (syn 1.0.72 {:#?} dump — same
                        output as vendors/SafeNet/src/process/rust_ast)
tools/extract_ast/      standalone CLI: .rs -> .ast (never touches vendors/)
verify/check.py         rustc gate + batch AST + preorder JSON + dedupe -> manifest
verify/report.py        out/report.md (stats, round-trip evidence, eval protocol)
verify/validate_format.py  CSV gate: header/columns/labels/row access + vocab info
build.py                runs the whole chain in order
splits/                 FROZEN real held-out split + scorer (see below)
├── make_splits.py      deterministic 70/10/20 split of testdata/ by
│                       (api, pattern), duplicate groups kept atomic
├── make_eval.py        -> gallery.json (fixed KB), test_pairs.csv,
│                       eval_manifest.json (per-pair provenance)
├── eval_protocol.py    audit / --pairs-preds / --retrieval-preds scorer
├── kb_verdicts.json    gold Y/M/N per (api, pattern) from the KB README
├── train.txt valid.txt test.txt   the frozen membership lists
└── README.md           method, sizes, leakage audit, protocol
```

## Outputs (`out/`)

| file | content |
|---|---|
| `pairs_manifest.jsonl` | one row per snippet: source, api, pattern_id, replaceability (Y/M/N), verdict (replaceable/conditional/irreplaceable/encapsulatable), contract, variant, verification{compile,…}, ast_len, seq_sha256, ok/dropped |
| `train_synth.csv` | synthetic-only within-API pairs (ablation: *synthetic only*) |
| `train_real.csv` | real (KB + train-split GitHub) within-API pairs — clean *real-only* ablation |
| `train_mixed.csv` | real (KB + train-split GitHub) + synthetic pairs — the *train on synthetic + real* formula |
| `train_hard.csv` | cross-API negatives, all label −1 (same pattern id across APIs = adversarial) |
| `report.md` | statistics + evidence + evaluation protocol |

All CSVs carry the byte-identical shipped header `,text1,text2,label` and the
`converttrainset.py` label semantics (1 = same (api, pattern), else −1),
balanced 50/50, shuffled with seed 1234.

The training CSVs are built from `splits/train.txt` + the KB only; valid and
test are never paired. Six train-split files whose normalized sequence is
identical to a valid/test sequence are dropped, and
`splits/check_train_leakage.py` must print `OK` for every CSV before training.
The shipped `vendors/SafeNet/.../train.csv` is **not** clean: it contains 25
test and 23 valid snippets, so it is a format reference, not a baseline.

## Label taxonomy (FP-reduction vector)

| verdict | meaning | example rules |
|---|---|---|
| replaceable (Y) | known safe replacement exists and compiles | Box::from_raw p4/p5/p6, ptr::copy p1, assume_init p1, as_ref p1, ptr::deref p1 (raw_ptr_deref), ptr::read p1, ptr::write_bytes p1, offset_from p1, Vec::from_raw_parts p4/p6, CStr::from_ptr p4, CString::from_raw p4/p6, transmute p3, unchecked family (get_unchecked_mut/unchecked_add/unchecked_mul/unwrap_unchecked), injections |
| conditional (M) | safe replacement exists but restructures / costs | assume_init p4, set_len p1/p2/p3, Box::from_raw p2, transmute p5 |
| irreplaceable (N) | no safe replacement in this frame | Box::from_raw p1/p3, ptr::copy p2, as_ref p2, ptr::write p2, transmute p4/p6, ptr::deref p2, ptr::read p2, ptr::write_bytes p2, offset_from p2, Vec::from_raw_parts p1, CStr::from_ptr p1, CString::from_raw p1 |
| encapsulatable | unsafe kept, wrapped in a checked `pub unsafe fn` with `assert!` + SAFETY docs | encap variants of every N/M rule |

Pattern ids and Y/M/N assignments follow
`vendors/SafeNet/knowledgebase/README.md` exactly.

## Verification gates (all CPU-local)

1. `rustc --edition 2021 --crate-type=lib --emit=metadata` — every snippet,
   100 % required (fail ⇒ build aborts).
2. `syn 1.0.72` parse of every snippet (the baseline AST entry point).
3. Preprocess to preorder JSON; exact-sequence dedupe within (api, kind);
   compile-broken files can never reserve a sequence slot.
4. CSV format gate vs the shipped `train.csv`.

## Findings from this dataset (matters for the research vectors)

1. **98.0 % round-trip identity** (583/595 real snippets): re-processing the
   real corpora through `extract_ast` + `pipe/preprocess` produces sequences
   found *verbatim* in the shipped `train.csv` — the pipeline is format-faithful.
2. **The baseline representation is extremely lossy**: type-only and
   name-only grid variants (e.g. `i32` vs `u64` parameterizations) normalize
   to *identical* sequences (`varN`), so 1164 generated snippets collapse to
   141 distinct training rows. Only *structural* changes create new rows —
   direct empirical support for the GNN/flattening vector in
   `notes/research/research-vectors.md`.
3. The committed `simplifyast.py` renames *all* idents, but the shipped CSV
   keeps known idents literal (`mem`, `transmute`, `NonNull`) — so the port in
   `pipe/preprocess.py` applies the ident filter found in the sibling
   `astsimpletree.py`. The baseline's `str.replace` prefix-collision quirk
   (which produced `var7llocator` in `train.csv`) is preserved deliberately.
4. 19 GitHub testdata files fail `syn` parsing (lex errors / truncation) —
   pre-existing source defects, skipped identically to how they must have been
   skipped in the original corpus build.

## Scientific protocol (from the theory note — read before claiming numbers)

- Train on synthetic or mixed; **validate/test only on real, held-out data**.
- The held-out real data is **frozen** in `splits/` (see `splits/README.md`):
  `testdata/` split 70/10/20 → train=288 / valid=69 / test=97 usable files,
  stratified by (api, pattern). Same-API leakage is 0; six cross-API duplicate
  sequences are removed from the training CSVs at the sequence level.
  The knowledgebase stays a fixed retrieval gallery.
- Ablations: real-only (`train_real.csv`, **not** the shipped `train.csv`) /
  synthetic-only (`train_synth.csv`) / real+synthetic (`train_mixed.csv`) /
  +hard negatives (`train_hard.csv`). Select on `valid` with
  `python splits/eval_protocol.py --split valid --pairs-preds <your.csv>`;
  score `test` **once** with `--split test` (pair metrics + per-pattern recall)
  or `--retrieval-preds <json>` (gallery retrieval).
- The valid pair set is only **10 pairs (5 pos / 5 neg)** and has no both-N
  pairs, so it is a weak selection signal and cannot estimate the safety FP
  rate. Prefer grouped CV on train for tuning and report the valid/test sample
  sizes with every number.
- Report FP rate on `verdict=irreplaceable` (N) snippets separately —
  gold verdicts live in `splits/kb_verdicts.json`.
- Never report a synthetic-measured number as a result.
- Pair-model plan and current blockers:
  [notes/research/bert-pair-model.md](../../notes/research/bert-pair-model.md).
- Before any run: `python splits/make_splits.py --check` must print `OK`
  three times (the freeze did not drift), and
  `python splits/check_train_leakage.py` must print `OK` for every training CSV.

## Limitations / phase 2

- Strategies C (LLM generation) and D (verification-guided preference pairs)
  are intentionally out of scope here; when added, gate them with the same
  `verify/check.py` manifest schema (`verification.miri/tests/clippy` fields
  already exist, currently `null`).
- MIRI not run (rustc-only gate); injected code is construction-safe but not
  UB-proven.
- Identifier renaming is *not* a data-augmentation axis under this
  representation — it is normalized away. Structural wrappers are the axis
  that works.
- `slice::from_raw_parts` is deliberately **not** covered: it has no entry in
  `vendors/SafeNet/knowledgebase/README.md`, and the protocol requires pattern
  ids and Y/M/N assignments to follow that KB exactly. Adding it would need a
  KB amendment first.
