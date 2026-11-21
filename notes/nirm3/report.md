# NIRM 3 — supervisor report

> **Status: draft for supervisor review · 18 November 2026**
>
> Work window: `01.09.2026 – 08.11.2026`
> Report window: `09.11.2026 – 22.11.2026`
> Code under test: `00f83e9` (detector fix + evaluation artifacts); the
> earlier data/report snapshot is `303e12d`. `safeify-data/transitions/` work is committed separately at `66e8dcf`. Frozen split hashes are in
> `safeify-data/synth/splits/eval_manifest.json`.
>
> This report supersedes the archived v1/v2/v3 notes. It reports the
> 2026-11-18 rerun after the `ptr::read` fix, not the non-reproducible v3 table.

## Summary

NIRM 3 delivered a working **replaceable-unsafe detector** and a frozen
real-data evaluation, not a safety oracle. The detector is a pure-Python
unsafe-region inventory plus `rust-analyzer` hover evidence, with an optional
`rustc --emit=metadata` gate. On the 97-file frozen test split it evaluates 105
sinks from 68 `(api, pattern)` cells.

The current LSP run is:

- accuracy **0.2000** (21/105);
- `FP-on-N` **0/27** — no gold-irreplaceable sink is predicted `Y` on this
  run (it was 2/27 before the fix; see §7.5);
- `recall_N` **0.3704 (10/27)**; `Y` precision **1.0000** (2 Y predictions);
- **17** decisive claims (coverage 0.1619), **12** with the right verdict and
  **10** with the right pattern; risk among claims **0.2941**;
- abstention rate **0.8381 (83.81%)**.

Two limitations remain reportable: the test split has been reused across
bug-fix iterations, and `rust-analyzer` evidence is timing-sensitive, so a
handful of verdicts move between runs (§7.6). DoD #3 is now scored by exporting
detector pattern hints as retrieval predictions; that number is a lower bound,
not a retrieval model (§5.3).

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
  spec_db.py     42 rule cells from safeify-data/synth/rules/*.yaml + 19 APIs
                 + gold Y/M/N from safeify-data/synth/splits/kb_verdicts.json
  verdict.py     family table + evidence -> Y/M/N, confidence, reason,
                 safe_alternative, encapsulate hint, pattern_hint
  verify.py      optional rustc --emit=metadata gate
```

Outputs are per-sink `Y/M/N` verdicts, not patches. `safe_alternative` is a
suggestion string. `--no-lsp` runs the same engine without hover evidence.

The suite is **8/8** on 2026-11-18 (7/7 before the `ptr::read` regression test
was added). The LSP end-to-end test was made deterministic (it previously used
`next(glob(...))`, whose filesystem order changed between runs and selected a
pattern-2 snippet that correctly abstains).

`verdict.py` now separates a **local owner** (KB p1/p5 `Y` shapes:
`let this = ManuallyDrop::new(self); ptr::read(&this.inner)`) from a
**`&`-borrow rooted at a parameter or `self`** (KB p2 `N` shape:
`ptr::read(&self.entries[i])`). `_param_names()` recovers parameter names from
the syntactic signature; a `&a as *const _` cast is still treated as raw-pointer
evidence and is not turned into `N`.

## 4. Data and evaluation protocol

- Corpus: `vendors/SafeNet/testdata/` — 474 `.rs` files; 454 usable after
  `syn` parsing and baseline preprocessing; 20 excluded (documented per file in
  [splits/README.md](../../safeify-data/synth/splits/README.md)).
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
- Scorer: `safeify-ai/score_frozen.py`; metrics are per sink against the
  file-level gold.
- **Test reuse caveat:** the test split was used for v1 -> v2 -> v3 bug fixes.
  “Report test once” and “nothing tuned on test” are not accurate. The current
  run is exploratory until a fresh holdout is carved or the reuse is formally
  disclosed.

## 5. Current results (2026-11-18, post-fix)

Run `00f83e9` on the frozen test split (97 files, 136 detected sinks, 105
evaluated). Relative to the previous report (`303e12d`) two `ptr::read` sink
verdicts changed because of the fix; six `from_raw`/`CStr` verdicts also differ
between the two reports, but those are `rust-analyzer` run variance, not code
changes (quantified in §7.6).

> **Inventory note (2026-11-20).** The numbers in §5 were measured with the text
> inventory (`inventory.py`). The detector now consumes the semantic inventory
> (`safeify-lint --inventory`), so the same frozen protocol re-run gives
> **139 sinks / 109 evaluated, accuracy 0.1927 (21/109), FP-on-N 0/28** — the
> correct count is unchanged and four newly visible sites abstain. Parity and
> attribution: [engine.md §6b](../research/engine.md#6b-the-frozen-inventory-is-semantic-now).

### 5.1 LSP mode

| Metric | Value |
|---|---:|
| Accuracy | 0.2000 (21/105) |
| `FP-on-N` (gold N -> pred Y) | **0/27** |
| `recall_N` | 0.3704 (10/27) |
| Y predictions / precision | 2 / 1.0000 |
| Decisive claims (coverage) | 17/105 (0.1619) |
| Errors among claims (risk) | 5 / 0.2941 |
| Pattern claims / correct | 17/105, 10 correct (0.5882) |
| Abstention (`M`) rate | 0.8381 (83.81%) |

Per class:

| Gold | Support | Precision | Recall | F1 |
|---|---:|---:|---:|---:|
| Y | 69 | 1.0000 | 0.0290 | 0.0563 |
| M | 9 | 0.1023 | 1.0000 | 0.1856 |
| N | 27 | 0.6667 | 0.3704 | 0.4762 |

Macro-F1 **0.2394**.

File-clustered bootstrap 95% intervals (2,000 resamples of *files*, not sinks):
accuracy **[0.1238, 0.2925]**, `recall_N` **[0.1724, 0.6000]**, macro-F1
**[0.1583, 0.3923]**. `FP-on-N` is 0/27 in every resample, which is a property
of this run, not a guarantee on unseen code (§8).

**Risk–coverage.** All 17 claims are emitted with `high` confidence, so the
curve degenerates to one operating point: coverage 0.1619, risk 0.2941. Split
by predicted class, the two `Y` claims are both correct (risk 0.0000) and the
15 `N` claims carry all five errors (risk 0.3333). Confidence is binary, so
there is no real coverage/risk knob yet; graded scores are NIRM 4 work.

### 5.2 No-LSP mode

| Metric | Value |
|---|---:|
| Accuracy | 0.1238 (13/105) |
| `FP-on-N` | **0/27** |
| `recall_N` | 0.0741 (2/27) |
| Y predictions / precision | 2 / 1.0000 |
| Decisive claims (coverage) | 4/105 (0.0381) |
| Errors among claims (risk) | 0 / 0.0000 |
| Pattern claims / correct | 4/105, 3 correct (0.7500) |
| Abstention (`M`) rate | 0.9619 (96.19%) |

Macro-F1 **0.1193**; 95% intervals: accuracy **[0.0588, 0.2020]**,
`recall_N` **[0.0000, 0.2400]**, macro-F1 **[0.0700, 0.2413]**. No-LSP makes
only four claims, so its zero risk is close to vacuous.

### 5.3 DoD #3: retrieval on the frozen test split

`eval_protocol.py --retrieval-preds` expects `{id, pattern_id}` per test file.
The detector has no retrieval model, so `detect/export_retrieval.py` exports the
**modal sink `pattern_hint`** per file (files without a hint get `0`, counted as
a miss). This is a documented substitution and a **lower bound**, not a
retrieval result.

| Mode | Queries | Files with a claim | Top-1 pattern accuracy | Macro per-API recall | Recall on `N` queries |
|---|---:|---:|---:|---:|---:|
| LSP | 97 | 22 (0.227) | 0.0928 | 0.0988 | 5/23 = 0.2174 |
| No-LSP | 97 | 7 (0.072) | 0.0206 | 0.0159 | 1/23 = 0.0435 |

Note the denominator change: retrieval is scored per **file/snippet** (23
`verdict=N` snippets), while §5.1 counts **sinks** (27 `verdict=N` sinks).

### 5.4 Baselines on the same 105 sinks

Constant-`Y` gives accuracy **0.657** and macro-F1 **0.265**, but 27
`FP-on-N` — it is not a usable detector. Constant-`M` gives accuracy **0.086**.
The headline accuracy (0.2000) is still below the constant-`Y` baseline, so it
is not evidence of usefulness; the operative result is the selective one: 17
claims, 12 correct verdicts, 10 correct patterns, 0 dangerous-direction errors.

### 5.5 Pattern hints

17 hints are claimed, 10 correct (0.5882). The seven wrong hints are all p1
over-claims: `Box::from_raw/3-1` (p1 vs p3), `Box::from_raw/4-1` (p1 vs p4),
`CString::from_raw/3-4` (p1 vs p3), `CString::from_raw/4-4` (p1 vs p4),
`Vec::from_raw_parts/3-2` (p1 vs p3), `Vec::from_raw_parts/4-3` (p1 vs p4), and
`ptr::read/5-3` (p1 vs p5). Pattern classification beyond p1 needs dataflow;
NIRM 3 does not attempt it.

Five claims are `N` where gold is `Y` (conservative direction, not dangerous):
`Box::from_raw/4-1`, `CString::from_raw/4-4`, `Rc::from_raw/1-1`,
`Rc::from_raw/1-3`, `Vec::from_raw_parts/4-3`. All come from the p1-only
assumption in the reconstruction (`from_raw*`) rule, which reads any raw
pointer argument as pattern 1.

## 6. Why the headline accuracy is misleading

- 3-way accuracy (0.2000) is still below the constant-`Y` baseline (0.657), so
  accuracy alone cannot support a usefulness claim.
- 0.8381 (83.81%) of sinks are `M` abstentions; the detector is silent on most
  of the corpus.
- The useful quantity is the **selective** one: 17 decisive claims, 12 correct,
  precision 0.7059 among claims, and 0 dangerous-direction errors.
- File-clustered intervals are now reported (§5.1); with 105 sinks and 17
  claims the uncertainty is wide (accuracy CI spans 0.12–0.29), and resampling
  *sinks* would understate it because 105 sinks come from 97 files.
- The test split has been reused, so even these exploratory numbers are
  optimistic relative to a truly unseen corpus; they are not a held-out result.
- `rust-analyzer` verdict noise adds a run-to-run component that the statistical
  interval does not capture (§7.6).

## 7. Failure analysis

1. **Gold-Y remains mostly `M`:** 62/69 gold-Y sinks are predicted `M` and 5
   are `N`. The classifier is p1-shaped; patterns needing inter-procedural
   dataflow are deliberately left for NIRM 4. This is a design limitation, not
   a bug.
2. **Gold-N recall is low:** 17/27 gold-N sinks remain `M`; the detector is
   conservative. The 10 correct N claims concentrate in `CStr::from_ptr`,
   `CString::from_raw`, `Rc::from_raw`, and `Vec::from_raw_parts`, where usable
   pointer evidence exists at the reconstruction site.
3. **Evidence quality is compilability-bound:** many SafeNet testdata files are
   fragments (WinRT FFI, truncated sources) that do not compile standalone;
   hover yields `{unknown}` and the sink stays `M`. The report must say this.
4. **Corpus defects:** 20 excluded files, 14 label-conflict duplicate groups,
   6 cross-API identical sequences, 31 `api_mismatch` sinks. No sensitivity
   analysis has been done for the excluded sinks.
5. **The `ptr::read/2-1.rs` false positive is fixed.** `owner_shaped` used to
   claim `Y` for `std::ptr::read(&self.entries[i])` because the indexed
   expression looked in-frame; the borrow is rooted at `&mut self`, so the
   owner is outside the frame and KB p2 applies (`N`). The rule now requires a
   *local* owner binding, so the p5 shapes `ptr::read(&v[i])`,
   `ptr::read(&this.inner)` and `ptr::read(&me.buf)` still return `Y`. Covered
   by `test_ptr_read_borrowed_param_n`; `FP-on-N` went 2/27 -> 0/27 in both
   modes.
6. **Verdicts are not fully reproducible run-to-run.** The previous report
   (`303e12d`) and this one differ on six `from_raw`/`CStr` sinks that the fix
   does not touch: `CStr::from_ptr/1-12` (`N` -> `M`),
   `CString::from_raw/3-4`, `CString::from_raw/4-4`, `Rc::from_raw/1-3`,
   `Vec::from_raw_parts/1-3`, `ptr::deref/4-8` (`M` -> `N`). Re-running three
   of those files three times produced one flip (`ptr::deref/4-8`) with no code
   change; the mechanism is `ra_client` hover/diagnostics timeouts (15 s
   request, 45 s readiness) leaving `{unknown}` evidence on a slow start. The
   effect is confined to the raw-pointer-evidence family and is bounded by
   ±6 sinks here, but it means a single run is not a stable measurement.
   Recommended follow-up: cache hover evidence per file, or fail the run when
   readiness times out instead of silently degrading to `M`.
7. **The LSP e2e test was order-dependent** until 2026-11-18; the fix selects
   sorted pattern-1 snippets. One further run in the same session failed
   transiently without a reproducible snippet-level difference; three
   consecutive reruns and six snippet-level repetitions passed. Treat the RA
   path as timing-sensitive and rerun before quoting `8/8`.

## 8. Safety claim

After the fix, both LSP and no-LSP modes have **`FP-on-N` 0/27** on this frozen
run, so the dangerous-direction claim is now true *for this run*. It is still
not a safety oracle:

> On the frozen test split the detector abstains on 83.81% of sinks and makes
> 17 decisive claims, none of them a `Y` on a gold-irreplaceable sink. Five
> claims are `N` where gold is `Y` (over-conservative, not dangerous), and
> `rust-analyzer` timing can move a few verdicts between runs.

A claim of the form "no dangerous false positives" must therefore be scoped to
the split, the run and the pinned toolchain, and must be repeated after any
verdict-engine change. It must not be presented as a property of the analyzer
on unseen code; recall is 0.3704, so most irreplaceable sinks are never
flagged.

## 9. Reproducibility

Environment used for this run:

- Python 3.13.5, repo `.venv`;
- `rustc 1.100.0 (0ef1bc386 2026-11-09)`;
- `rust-analyzer 0.3.3025-standalone` (2026-08-24 release), pinned under
  `.tools/ra-bin` (gitignored), with the `rust-src` shim from
  `safeify-ai/setup_rust_src.sh`;
- frozen split hashes in `safeify-data/synth/splits/eval_manifest.json`
  (train `589261…`, valid `cd9473…`, test `0b242a…`).

Commands:

```bash
cd research
export PATH="$PWD/.tools/ra-bin:$PATH"
export HOME="$PWD/.tools/ra-home"
export RUSTUP_HOME=/home/user/.rustup CARGO_HOME=/home/user/.cargo
source .venv/bin/activate
python safeify-ai/test_detect.py
python safeify-data/synth/splits/make_splits.py --check
python safeify-data/synth/splits/check_train_leakage.py

T=safeify-data/synth/splits/test.txt
sed "s|^|vendors/SafeNet/testdata/|" "$T" | tr '\n' '\0' \
  | xargs -0 python -u safeify-ai/detect.py --json safeify-ai/out/nirm3_eval_lsp.json

python safeify-ai/score_frozen.py --report safeify-ai/out/nirm3_eval_lsp.json \
  | tee safeify-ai/out/nirm3_eval_lsp_score.txt
python safeify-ai/export_retrieval.py safeify-ai/out/nirm3_eval_lsp.json \
  --out safeify-ai/out/nirm3_retrieval_lsp.json
python safeify-data/synth/splits/eval_protocol.py --retrieval-preds \
  safeify-ai/out/nirm3_retrieval_lsp.json | tee safeify-ai/out/nirm3_retrieval_score.txt
```

Artifacts: [LSP raw JSON](../../safeify-ai/out/nirm3_eval_lsp.json),
[no-LSP raw JSON](../../safeify-ai/out/nirm3_eval_nolsp.json),
[combined score](../../safeify-ai/out/nirm3_eval_score.txt),
[LSP score](../../safeify-ai/out/nirm3_eval_lsp_score.txt),
[no-LSP score](../../safeify-ai/out/nirm3_eval_nolsp_score.txt),
[LSP retrieval preds](../../safeify-ai/out/nirm3_retrieval_lsp.json),
[retrieval score](../../safeify-ai/out/nirm3_retrieval_score.txt).

The detector fix and these artifacts are committed at `00f83e9`; the earlier
data/report snapshot is `303e12d`. `safeify-data/transitions/` work is committed
separately at `66e8dcf` and is not part of this result. The frozen split is
stable; re-run if the pinned rust-analyzer or the split changes.

## 10. Limitations

- No AST traversal and no MIR/borrowck; hover/type evidence only.
- No inter-procedural dataflow; pattern classification beyond p1 is not
  attempted.
- `M/low` is the default, so the tool abstains on most sinks (83.81%).
- LSP evidence depends on the file compiling in a detectable crate context; one
  rust-analyzer process per file (~10 s/file here), no repo-scale batching.
- `rust-analyzer` timeouts make a few verdicts run-dependent (§7.6); a single
  run is not a stable measurement.
- `safe_alternative` is a suggestion string, not an automated patch.
- MIR/borrowck is not implemented and currently has no owning milestone.
- Results are verdict-level; retrieval is a `pattern_hint` export, not a
  retrieval model.
- Test reuse and 3 both-N pairs limit any safety-FP conclusion.

## 11. Pair-model data readiness (handoff note)

*(Dated 2026-11-18. The BERT/SafeNet-style pair model is a separate line, not
NIRM 4 — the dissertation plan assigns NIRM 4 to ML warning classification.)*

The BERT/SafeNet-style pair model is **not NIRM 3**. The 2026-11-18
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

Remaining pair-model blockers: valid pair set is only 10 pairs (5 pos / 5 neg); the
test pair set is 76 pairs with 3 both-N pairs; no BERT training pipeline runs
out of the box (vendor `train.sh` references a missing `main.py`, removed
`transformers.AdamW`/`pad_to_max_length`, and an absent `bert_wwm_mlm`
checkpoint); no GPU (CPU-only, ~62.7 s per BERT-base forward at batch 16 x 100
tokens in a synthetic benchmark).

> *2026-11-21 supersession: the enlarged full pair sets (839 valid / 1,283 test
> pairs, 34 / 44 both-N negatives) replace the 10/76-pair selection and
> reporting numbers above; see
> [`safeify-data/synth/splits/README.md`](../../safeify-data/synth/splits/README.md).
> The pipeline blockers in this paragraph still stand.*

The chosen first path is a **frozen-BERT embedding cache + pair head**: BERT
encodes each unique snippet once, the vectors are cached, and only a small
comparator is trained. It is CPU-feasible and gives a clean baseline, but it
does not fine-tune BERT. See
[bert-pair-model.md](../research/bert-pair-model.md) for the plan, open
decisions, and gates. No model has been trained.

## 12. Conclusion and next actions

NIRM 3 has a working detector, a frozen protocol, a passing suite (8/8), and an
honest preliminary evaluation with per-class metrics and clustered intervals.
It does **not** support a general safety claim, and the AST/MIR scope deviation
requires supervisor approval.

Done before this draft:

1. ~~Fix the `owner_shaped` `ptr::read` false positive~~ — done at `00f83e9`
   (`FP-on-N` 2/27 -> 0/27 in both modes), with a regression test.
2. ~~Add per-class precision/recall/F1, coverage, risk–coverage, clustered
   intervals~~ — done in `score_frozen.py` and §5.
3. ~~Run DoD #3 retrieval scoring~~ — done as a `pattern_hint` export (§5.3).

Still required for sign-off:

4. Decide explicitly whether to carve a fresh holdout or disclose test reuse.
   This report discloses it; the disclosure must be accepted in writing.
5. Produce the 4-page paper outline for the 25.11 venue slot.
6. Get written approval for the AST/MIR re-scope, or add a MIR milestone.
7. Accept the DoD #3 substitution (`pattern_hint` export, not retrieval) or
   request a retrieval model, which moves the item to NIRM 4.
8. Decide whether `rust-analyzer` verdict variance is acceptable for the
   reported numbers or whether evidence caching must land first.

The three decisions are drafted for sending in
[signoff-request.md](signoff-request.md).

The BERT pair model is a separate line, not NIRM 4; its data gate and
valid-split path are in place, and the frozen-BERT cache plan is in
[bert-pair-model.md](../research/bert-pair-model.md). No model has been trained.
