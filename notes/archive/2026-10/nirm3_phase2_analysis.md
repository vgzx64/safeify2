# НИРМ 3 — Phase 2 analysis (2026-10-19)

> **ARCHIVED — historical only.** Superseded by
> [notes/nirm3/results.md](../../nirm3/results.md). These v3 numbers do not
> reproduce on the 2026-10-24 tree (current `FP-on-N` is nonzero); do not cite
> them as final results.

Follow-up to `notes/nirm3_phase1_results.md`. Phase 2 = interpret the numbers,
fix what is a *bug* (not tune), re-run, produce the analysis that goes into the
supervisor report. Raw outputs: `/tmp/nirm3_score_v3.txt`,
`/tmp/nirm3_lsp_v3.json`, `/tmp/nirm3_no_lsp_v2.json`.

## 1. Verdict-engine bugs found & fixed (v1 → v3)

All three are violations of the invariant "claims Y/N only with real evidence"
(`research/detect/README.md`):

1. **Evidence-free Y on transmute (v1 no-lsp).**
   `all(_PRIM_TY.match(p) for p in prim if p)` skipped missing types → matched
   vacuously when *no* type evidence existed → every syntactic transmute was
   `Y/high, hint=p1`. This produced the v1 no-lsp **FP-on-N**
   (`mem::transmute_copy/6-2.rs`, gold p6=N, WinRT FFI types, claimed
   "scalar-to-scalar `as` cast"). Fix: Y requires ≥2 known type slots
   (src+dst) and all primitive.
2. **Raw hover text in family rules.** `reconstitute`/`borrow_ffi`/`ptr::read`
   matched `_PTR_TY`/`_REF_TY` against raw hover blobs (`"let dest: *mut
   {unknown}"` starts with `l` → never matched) → gold-N cases stayed `M`.
   Fix: `_type_of_hover` normalization applied once at `decide()` entry.
3. **`_type_of_hover` prefix regex** `^[A-Za-z_]\w*:` could not parse
   let-statement hovers (`let dest: *mut u8` — space after `let`) → fix 2 was
   a no-op until this was fixed. Now `^(?:let\s+|ref\s+)?[A-Za-z_]\w*:\s*(.+)$`.

Unit-validated: `let dest: *mut {unknown}` → `N high, kb_gold=N`;
evidence-free transmute → `M low, hint=None`; `test_detect.py 7/7`.

## 2. Final numbers (frozen test, 97 files / 136 sinks / 105 evaluated)

| metric | no-lsp v2 | lsp v1 | **lsp v3 (final)** |
|---|---|---|---|
| accuracy (3-way) | 0.086 (9/105) | 0.133 (14/105) | **0.162 (17/105)** |
| FP-on-N (gold N → pred Y) | 0 | 0 | **0/27** |
| recall_N (gold N → pred N) | 0.000 | 0.185 | **0.296 (8/27)** |
| Y predictions / precision | 0 / — | 4 / — | 4 / — |
| pattern claims (correct) | 0 | 6 (5, 0.83) | 10 (5, 0.50) |
| confusion (gold→pred) | all-M except gold-M | Y:0/68/1 N:0/22/5 | Y:0/67/**2** N:0/**19**/**8** |

Per-family (lsp v3): `vec_len 4/5`, `borrow_ffi 3/6`, `reconstitute 9/21`,
`rawmem 1/54`, `ptr_arith 0/6`, `transmute 0/7`, `rawref 0/4`, `zeroed 0/2`.

## 3. Reading / failure analysis

1. **Safety-first behavior confirmed:** 0 dangerous FPs on irreplaceable code
   in every LSP configuration — the `research_vectors.md` FP-reduction target
   holds. Purely syntactic mode is near-useless once evidence-free claims are
   removed (accuracy 0.086) — quantifies the value of RA type evidence.
2. **The 67 gold-Y → M wall** is the documented p1-only/dataflow limitation:
   `ptr::copy*`, `ptr::read/write`, `offset_from`, `transmute` p2/p3 patterns
   need inter-procedural dataflow (NIRM 4 ML handoff), not syntax.
3. **New limitation surfaced by the fix:** raw-ptr evidence now claims `N`
   with `hint=p1`, which is wrong on p3/p4 files whose gold is `N`/`Y`
   respectively (2 gold-Y → pred-N; 5 wrong hints). Same root cause: a single
   p1-shaped rule cannot separate the KB's 4–6 patterns per API.
4. **Evidence quality caveat:** many SafeNet testdata files are fragments
   (WinRT FFI etc.) that do not compile standalone → hover yields `{unknown}`
   → sink stays `M`. Report must state LSP evidence depends on compilability.
5. **Corpus defects (from `splits/stats.json`, unchanged):** 20 excluded files
   (`no_cached_sequence` 19, `no_pattern_id` 1), 14 label-conflict duplicate
   groups (e.g. `ptr::copy/4-13.rs` byte-identical to `ptr::copy/1-2(4-14).rs`
   with different pattern ids), 6 cross-API identical sequences, 31 extra
   sinks in multi-API files excluded from scoring (`api_mismatch`).

## 4. Limitations list (goes into the report)

- Classifier is p1-shaped; patterns >1 need dataflow (by design, NIRM 4).
- `M/low` default dominates; analyzer optimizes FP-on-N, not accuracy.
- LSP evidence requires compilable files; fragments degrade to `M`.
- One RA process per file (~2.6–9.4 s); no repo-scale batching yet.
- `safe_alternative` is a suggestion string; no automated patching.
- Numbers are verdict-level (per sink vs file gold); pattern-id retrieval as
  such is not attempted — that is the ML component's task in NIRM 4.

## 5. Reproduce (v3)

```bash
cd research && source ../.venv/bin/activate
python detect/test_detect.py                      # 7/7
T=synth/splits/test.txt
sed "s|^|../vendors/SafeNet/testdata/|" $T | tr '\n' '\0' \
  | xargs -0 python -u detect/detect.py --json /tmp/nirm3_lsp_v3.json
sed "s|^|../vendors/SafeNet/testdata/|" $T | tr '\n' '\0' \
  | xargs -0 python -u detect/detect.py --no-lsp --json /tmp/nirm3_no_lsp_v2.json
python detect/score_frozen.py --report /tmp/nirm3_lsp_v3.json \
    --report2 /tmp/nirm3_no_lsp_v2.json | tee /tmp/nirm3_score_v3.txt
```
