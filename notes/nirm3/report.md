# NIRM 3 — supervisor report

> **Status: draft for supervisor review · 18 November 2026**
>
> Work window: `01.09.2026 – 08.11.2026`
> Report window: `09.11.2026 – 22.11.2026`
> Code under test: `303e12d` (NIRM 3/detector/data changes committed);
> later documentation commits follow. Unrelated pre-existing
> `research/transitions/` work remains dirty. Frozen split hashes are in
> `research/synth/splits/eval_manifest.json`.
>
> This report supersedes the archived v1/v2/v3 notes. It reports the
> 2026-11-18 rerun, not the non-reproducible v3 table.

## Summary

NIRM 3 delivered a working **replaceable-unsafe detector** and a frozen
real-data evaluation, not a safety oracle. The detector is a pure-Python
unsafe-region inventory plus `rust-analyzer` hover evidence, with an optional
`rustc --emit=metadata` gate. On the 97-file frozen test split it evaluates 105
sinks from 68 `(api, pattern)` cells.

The current LSP run is:

- accuracy **0.1714** (18/105);
- `FP-on-N` **2/27** — gold-irreplaceable sinks predicted `Y` (the
  dangerous direction);
- `recall_N` **0.2593 (7/27)**; `Y` precision **0.5000** (4 Y predictions);
- **14** decisive claims, **9** with the right
  verdict and **7** with the right pattern;
- abstention rate **0.8667 (86.67%)**.

Two sink-level false positives remain, both in
`vendors/SafeNet/testdata/ptr::read/2-1.rs`, so the earlier “no dangerous false
positives” claim is **not true**. The test split has also been reused across
bug-fix iterations. These are reportable limitations, not footnotes.

## 1. Formal task

From [papers/my_dissertation_plan.md](../../papers/my_dissertation_plan.md):

> *НИРМ 3. Реализация базового статического анализатора на основе AST и MIR
> компилятора Rust. Апробация анализатора на тестовых наборах данных и
> публикация предварительных результатов.*

The formal task names an **AST and MIR** analyzer. The delivered system is
neither: it masks `unsafe` regions at source level, inventories sink calls
against a spec database, and asks `rust-analyzer` for hover/type evidence. There
is no direct AST traversal and no MIR.

## 2. Scope decision (requires supervisor approval)

The internal decision was to treat the `rust-analyzer`-based implementation as
an accepted alternative and defer full MIR/borrowck to NIRM 4. That decision is
**not yet documented as approved**, and NIRM 4's formal scope is ML models
(Gradient Boosting / Random Forest), not MIR. MIR currently has no owning
milestone.

This report therefore makes the deviation explicit:

1. The detector is a *source-level, evidence-backed* analyzer, not an AST/MIR
   analyzer.
2. The RA hover evidence is `type`/HIR-adjacent, not MIR dataflow.
3. If the supervisor requires literal AST+MIR, NIRM 3 is incomplete regardless
   of the detector's numbers; a MIR work package must be added to NIRM 4 or a
   separate milestone.

Do not present the re-scope as settled until it is accepted in writing.

## 3. What was implemented

```
.rs file
  inventory.py   unsafe { } / unsafe fn spans, sink calls, raw-deref fallback,
                 syntactic guards (null_check, assert, with_capacity, ...)
  ra_client.py   stable rust-analyzer over stdio -> hover evidence
                 (receiver / argument / return types)
  spec_db.py     42 rule cells from research/synth/rules/*.yaml + 19 APIs
                 + gold Y/M/N from research/synth/splits/kb_verdicts.json
  verdict.py     family table + evidence -> Y/M/N, confidence, reason,
                 safe_alternative, encapsulate hint, pattern_hint
  verify.py      optional rustc --emit=metadata gate
```

Outputs are per-sink `Y/M/N` verdicts, not patches. `safe_alternative` is a
suggestion string. `--no-lsp` runs the same engine without hover evidence.

The suite is **7/7** on 2026-11-18. The LSP end-to-end test was made
deterministic (it previously used `next(glob(...))`, whose filesystem order
changed between runs and selected a pattern-2 snippet that correctly abstains).

## 4. Data and evaluation protocol

- Corpus: `vendors/SafeNet/testdata/` — 474 `.rs` files; 454 usable after
  `syn` parsing and baseline preprocessing; 20 excluded (documented per file in
  [splits/README.md](../../research/synth/splits/README.md)).
- Frozen split: seed 1234, stratified by `(api, pattern_id)`, 70/10/20 ->
  train **288** / valid **69** / test **97** usable files.
  `make_splits.py --check` prints `OK`; same-API leakage is 0; six cross-API
  duplicate sequences and 14 label-conflict groups are documented.
- Gallery: `vendors/SafeNet/knowledgebase/` — 141 cached sequences over 18 APIs;
  never a query.
- Test: 97 files, **136 detected sinks**, **105 evaluated**; 31 sinks are
  excluded as `api_mismatch` because the file contains more than one API.
  Gold verdicts are per file from the KB; 105 sinks come from 97 files and 68
  cells, so the sample is clustered, not independent.
- Scorer: `research/detect/score_frozen.py`; metrics are per sink against the
  file-level gold.
- **Test reuse caveat:** the test split was used for v1 -> v2 -> v3 bug fixes.
  “Report test once” and “nothing tuned on test” are not accurate. The current
  run is exploratory until a fresh holdout is carved or the reuse is formally
  disclosed.

## 5. Current results (2026-11-18)

### LSP mode

| Metric | Value |
|---|---:|
| Accuracy | 0.1714 (18/105) |
| `FP-on-N` (gold N -> pred Y) | **2/27** |
| `recall_N` | 0.2593 (7/27) |
| Y predictions / precision | 4 / 0.5000 |
| Decisive claims | 14/105 |
| Pattern claims / correct | 14/105, 7 correct (0.5000) |
| Abstention (`M`) rate | 0.8667 (86.67%) |

Per class:

| Gold | Support | Precision | Recall | F1 |
|---|---:|---:|---:|---:|
| Y | 69 | 0.5000 | 0.0290 | 0.0548 |
| M | 9 | 0.0989 | 1.0000 | 0.1800 |
| N | 27 | 0.7000 | 0.2593 | 0.3784 |

Macro-F1: **0.2044**.

### No-LSP mode

| Metric | Value |
|---|---:|
| Accuracy | 0.1048 (11/105) |
| `FP-on-N` | **2/27** |
| `recall_N` | 0.0000 |
| Y predictions / precision | 4 / 0.5000 |
| Decisive claims | 4/105 |
| Pattern claims / correct | 4/105, 1 correct (0.2500) |

### Baselines on the same 105 sinks

Constant-`Y` gives accuracy **0.657** and macro-F1 **0.265**, but 27
`FP-on-N` — it is not a usable detector. Constant-`M` gives accuracy **0.086**.
The headline accuracy is therefore not evidence of useful classification; the
operative result is selective: 14 claims, 9
correct verdicts, 7 correct patterns.

### The false positives

Both current `FP-on-N` cases are the same file and expression:

```rust
// vendors/SafeNet/testdata/ptr::read/2-1.rs, lines 26 and 52
self.entries[j] = std::ptr::read(&self.entries[i]);
```

Gold is `ptr::read` **p2 = N**. The `owner_shaped` branch in
`research/detect/verdict.py` treats the dotted/indexed argument as an in-frame
owner and emits `Y/high` without concrete type evidence. This affects both LSP
and no-LSP modes and directly contradicts the earlier safety claim. At file
level it is 1/23 N files; at sink level it is 2/27.

A separate p1-only assumption in the reconstruction (`from_raw*`) rule produces
false `N` in LSP mode on three gold-Y files (`Box::from_raw/4-1.rs`,
`Rc::from_raw/1-1.rs`, `Vec::from_raw_parts/4-3.rs`): it assumes p1 whenever it
sees a raw pointer. These are conservative in direction but still wrong verdicts.

### Pattern hints

Only 14 pattern hints are claimed (7 correct, 0.5000), and several are p1-biased:
`Box::from_raw/3-1` (p1 vs p3), `Box::from_raw/4-1` (p1 vs p4),
`Vec::from_raw_parts/3-2` (p1 vs p3), `Vec::from_raw_parts/4-3` (p1 vs p4),
`ptr::read/2-1` (p1 vs p2, twice), and `ptr::read/5-3` (p1 vs p5). Pattern
classification beyond p1 needs dataflow; NIRM 3 does not attempt it.

## 6. Why the headline accuracy is misleading

- 3-way accuracy is below the constant-`Y` baseline (0.657), so accuracy alone
  cannot support a usefulness claim.
- 0.8667 (86.67%) of sinks are `M` abstentions; the detector is silent on most
  of the corpus.
- The useful quantity is the **selective** one: decisive claims, their
  precision, and the dangerous-direction FP rate.
- There are no confidence intervals or clustered bootstrap estimates. With 105
  sinks and 14 decisive claims, the uncertainty is large.
- The test split has been reused, so even these exploratory numbers are
  optimistic relative to a truly unseen corpus.

## 7. Failure analysis

1. **Gold-Y remains mostly `M`:** 65/69 gold-Y sinks are predicted `M`. The
   classifier is p1-shaped; patterns needing inter-procedural dataflow are
   deliberately left for NIRM 4. This is a design limitation, not a bug.
2. **Gold-N recall is low:** 18/27 gold-N sinks remain `M`; the detector is
   conservative. The correct N claims concentrate in `CStr::from_ptr`,
   `CString::from_raw`, `Rc::from_raw`, and `Vec::from_raw_parts`, where usable
   pointer evidence exists at the reconstruction site.
3. **Evidence quality is compilability-bound:** many SafeNet testdata files are
   fragments (WinRT FFI, truncated sources) that do not compile standalone;
   hover yields `{unknown}` and the sink stays `M`. The report must say this.
4. **Corpus defects:** 20 excluded files, 14 label-conflict duplicate groups,
   6 cross-API identical sequences, 31 `api_mismatch` sinks. No sensitivity
   analysis has been done for the excluded sinks.
5. **No intervals:** no confidence intervals or clustered bootstrap estimates.
6. **The LSP e2e test was order-dependent** until 2026-11-18; the fix selects
   sorted pattern-1 snippets. This does not change detector behavior, but it
   explains why the earlier “7/7” claim could not be trusted as pinned. One
   further run in the same session failed transiently without a reproducible
   snippet-level difference; three consecutive reruns and six snippet-level
   repetitions passed. Treat the RA path as timing-sensitive and rerun before
   quoting `7/7`.

## 8. Safety claim

The earlier statement “no dangerous false positives” is **false on the current
tree**. Two sink-level `FP-on-N` cases remain, in both LSP and no-LSP modes.
The correct claim is:

> The detector abstains on most sinks, and its decisive `N`/`M` claims are
> conservative, but it can emit `Y` on irreplaceable `ptr::read` field/index
> arguments. It is not a safety oracle.

Publishing a “zero FP” claim without fixing `owner_shaped` would be
misrepresentation.

## 9. Reproducibility

Environment used for this run:

- Python 3.13.5, repo `.venv`;
- `rustc 1.100.0 (0ef1bc386 2026-11-09)`;
- `rust-analyzer 0.3.3025-standalone` (2026-08-24 release), pinned under
  `.tools/ra-bin` (gitignored), with the `rust-src` shim from
  `research/detect/setup_rust_src.sh`;
- frozen split hashes in `research/synth/splits/eval_manifest.json`
  (train `589261…`, valid `cd9473…`, test `0b242a…`).

Commands:

```bash
cd research
export PATH="$PWD/../.tools/ra-bin:$PATH"
export HOME="$PWD/../.tools/ra-home"
export RUSTUP_HOME=/home/user/.rustup CARGO_HOME=/home/user/.cargo
source ../.venv/bin/activate
python detect/test_detect.py                 # 7/7
python synth/splits/make_splits.py --check   # OK, three times
python synth/splits/check_train_leakage.py   # OK (NIRM 4 data gate)

T=synth/splits/test.txt
sed "s|^|../vendors/SafeNet/testdata/|" "$T" | tr '\n' '\0' \
  | xargs -0 python -u detect/detect.py --json detect/out/nirm3_eval_lsp.json
sed "s|^|../vendors/SafeNet/testdata/|" "$T" | tr '\n' '\0' \
  | xargs -0 python -u detect/detect.py --no-lsp --json detect/out/nirm3_eval_nolsp.json

python detect/score_frozen.py --report detect/out/nirm3_eval_lsp.json \
  --report2 detect/out/nirm3_eval_nolsp.json \
  | tee detect/out/nirm3_eval_score.txt
```

Artifacts: [LSP raw JSON](../../research/detect/out/nirm3_eval_lsp.json),
[no-LSP raw JSON](../../research/detect/out/nirm3_eval_nolsp.json),
[LSP score](../../research/detect/out/nirm3_eval_lsp_score.txt),
[no-LSP score](../../research/detect/out/nirm3_eval_nolsp_score.txt).

The NIRM 3/detector/data changes are committed at `303e12d`; later
documentation commits follow. Unrelated pre-existing `research/transitions/`
work remains dirty. The frozen split is stable; re-run if those unrelated files
are meant to be part of the result.

## 10. Limitations

- No AST traversal and no MIR/borrowck; hover/type evidence only.
- No inter-procedural dataflow; pattern classification beyond p1 is not
  attempted.
- `M/low` is the default, so the tool abstains on most sinks.
- LSP evidence depends on the file compiling in a detectable crate context; one
  rust-analyzer process per file (~10 s/file here), no repo-scale batching.
- `safe_alternative` is a suggestion string, not an automated patch.
- MIR/borrowck is not implemented and currently has no owning milestone.
- Results are verdict-level, not pattern-retrieval results.
- Test reuse and 3 both-N pairs limit any safety-FP conclusion.

## 11. NIRM 4 handoff: BERT pair-model data readiness

The BERT/SafeNet-style pair model is **NIRM 4**, not NIRM 3. The 2026-11-18
data audit found that the then-current `train_mixed.csv` contained every
valid/test snippet (97/97 test, 69/69 valid), including 55/76 test pairs
verbatim. The training CSVs were rebuilt from `splits/train.txt` + KB only,
with sequence-level decontamination of six cross-API duplicates:

| file | pairs | label 1 | label -1 |
|---|---:|---:|---:|
| `train_synth.csv` | 2,628 | 1,314 | 1,314 |
| `train_real.csv` | 2,688 | 1,344 | 1,344 |
| `train_mixed.csv` | 8,580 | 4,290 | 4,290 |
| `train_hard.csv` | 1,000 | 0 | 1,000 |

`splits/check_train_leakage.py` now gates all four files; the shipped SafeNet
`train.csv` is also contaminated (25 test, 23 valid) and must not be used for a
held-out result.

Remaining NIRM 4 blockers: valid pair set is only 10 pairs (5 pos / 5 neg); the
test pair set is 76 pairs with 3 both-N pairs; no BERT training pipeline runs
out of the box (vendor `train.sh` references a missing `main.py`, removed
`transformers.AdamW`/`pad_to_max_length`, and an absent `bert_wwm_mlm`
checkpoint); no GPU (CPU-only, ~62.7 s per BERT-base forward at batch 16 x 100
tokens in a synthetic benchmark).

The chosen first path is a **frozen-BERT embedding cache + pair head**: BERT
encodes each unique snippet once, the vectors are cached, and only a small
comparator is trained. It is CPU-feasible and gives a clean baseline, but it
does not fine-tune BERT. See
[bert-pair-model.md](../research/bert-pair-model.md) for the plan, open
decisions, and gates. No model has been trained.

## 12. Conclusion and next actions

NIRM 3 has a working detector, a frozen protocol, a passing suite, and an
honest preliminary evaluation. It does **not** yet support a safety claim, and
the AST/MIR scope deviation requires supervisor approval.

Before sign-off:

1. Fix the `owner_shaped` `ptr::read` false positive using `valid` only; add a
   regression test for `ptr::read/2-1.rs`.
2. Either carve a fresh holdout or disclose test reuse in every table.
3. Add per-class precision/recall/F1, coverage, risk–coverage, and clustered
   intervals; do not headline 3-way accuracy.
4. ~~Record a clean commit and pin Python/rust-analyzer versions~~ — done:
   code/data committed at `303e12d`; `rust-analyzer 0.3.3025` pinned.
5. Produce the 4-page paper outline for the 25.11 venue slot.
6. Get written approval for the AST/MIR re-scope, or add a MIR milestone.

The BERT pair model remains NIRM 4 work; the data gate and valid-split path
are in place, and the frozen-BERT cache plan is in
[bert-pair-model.md](../research/bert-pair-model.md). No model has been trained.
