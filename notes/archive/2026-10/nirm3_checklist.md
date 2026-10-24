# НИРМ 3 — Checklist / Plan

> **ARCHIVED — historical only.** Superseded by
> [notes/nirm3/README.md](../../nirm3/README.md) and
> [notes/nirm3/results.md](../../nirm3/results.md). Do not cite these numbers.

> **Formal task** (`papers/my_dissertation_plan.md §6.3`):
> *НИРМ 3. Реализация базового статического анализатора на основе AST и MIR компилятора Rust. Апробация анализатора на тестовых наборах данных и публикация предварительных результатов.*
>
> - Work window: `01.09.2026 – 08.11.2026`
> - Report to supervisor: `09.11.2026 – 22.11.2026`
> - Created: `19.10.2026` (~20 days left at that date)
>
> **Scope decision (agreed):** `AST+MIR компилятора` is not mandatory. Accepted
> basis: `research/detect/` = `rust-analyzer LSP (type/HIR evidence) +
> rustc --emit=metadata gate + syntactic inventory`. Full MIR/borrowck is
> deferred to NIRM 4 with justification paragraph in the report.

## Phase 0 — Freeze & env fix [1 day] — ✅ done 2026-10-19

- [x] `python splits/make_splits.py --check` → `OK x3`
      (`train 288 / valid 69 / test 97`, `same_api leakage 0`) —
      re-run before every experiment
- [x] Fix LSP test to `7/7` — done (venv rebuilt with `uv` for py3.13;
      `rustup component add rust-analyzer` → RA 1.99.1 replaces broken
      `~/.local/bin` symlink; `test_detect.py 7/7`)
- [x] `sh detect/setup_rust_src.sh` — script bugs fixed (version parse under
      rustup, curl -L), sysroot farm rebuilt for 1.99.1
- [ ] `git add/commit` on branch `dev` — pending (needs explicit go-ahead)
- [x] **Bug fixed in `ra_client.open_file`:** project root honored only when
      the file is under its `src/` — testdata files now use detached temp
      crates (~60 s/file → ~2.6–9.4 s/file, hover actually works)

## Phase 1 — Апробация: run detector on frozen test — ✅ done 2026-10-19

- [x] **no-lsp baseline (v2 final):** 97 files, `Y=3 M=133 N=0` →
      `/tmp/nirm3_no_lsp_v2.json`, accuracy 0.086, FP-on-N 0
- [x] **lsp (v3 final):** 97 files, `Y=4 M=119 N=13` →
      `/tmp/nirm3_lsp_v3.json`, **accuracy 0.162, FP-on-N 0/27,
      recall_N 0.296, 10 pattern claims (5 correct)**
- [x] Scored via **`research/detect/score_frozen.py`** (verdict-level
      confusion vs frozen gold; per-family + per-API tables; details in
      `notes/nirm3_phase1_results.md` + `notes/nirm3_phase2_analysis.md`)
- [ ] `--pairs-preds` scoring (optional, if time)

## Phase 2 — Analysis: what numbers mean — ✅ done 2026-10-19 (see notes/nirm3_phase2_analysis.md)

- [x] Per-family breakdown (in `score_frozen.py`): `vec_len 4/5`,
      `borrow_ffi 3/6`, `reconstitute 9/21`, `rawmem 1/54`,
      `transmute 0/7`, `ptr_arith 0/6`
- [x] FP-on-N: 0/27 in every LSP config (v1 also 0; the single v1 no-lsp FP
      was a **bug**, fixed)
- [x] FN-on-Y: 67 gold-Y sinks stay M — documented p1-only/dataflow
      limitation → NIRM 4 ML handoff
- [x] **3 verdict-engine bugs found & fixed** (v1→v3): evidence-free
      transmute Y (`if p` vacuous match), raw-hover text in family rules
      (no `_type_of_hover`), `let x:` hover prefix not parsed. Unit-validated;
      `test_detect.py 7/7` after each
- [x] Failure catalog: 20 excluded, 14 label-conflict groups, 6 cross-API
      seqs, 31 `api_mismatch` sinks (from `splits/stats.json` + scorer)
- [x] Limitations list drafted (Phase 2 note §4)

**Acceptance:** numbers exist for the **test set once**; nothing tuned on test
(no training happens in NIRM 3).

## Phase 2 — Analysis: what numbers mean [2-3 days]

- [ ] Per-family breakdown: `unchecked (Y) / transmute / rawmem /
      reconstitute / borrow_ffi / vec_len`
- [ ] FP analysis on `N`: how many `N` snippets got `Y`?
      (target: ~0; conservative `M` is OK)
- [ ] FN analysis on `Y`: which `Y` stayed `M` for lack of evidence?
      (expected: dataflow-heavy non-p1 patterns)
- [ ] Failure catalog: `label_conflicts 14`, `excluded 20`, `cross_api 6`
      — cite from `splits/stats.json`
- [ ] Limitations list: `p1-only classification`, `M/low default`,
      `no auto-patch`, `RA cost (2–5s/file)`, `MIR deferred`

## Phase 3 — Отчет научному руководителю [3-4 days]

Write `notes/nirm3_report.md` (this IS the `09.11–22.11` deliverable):

- [ ] 1. Цель + re-scoping paragraph (why RA-LSP qualifies as AST/HIR alternative)
- [ ] 2. Архитектура diagram:
      `inventory → ra_client → spec_db (42 rules, 19 APIs) → verdict (Y/M/N) → verify`
- [ ] 3. Данные и протокол: frozen split table, gallery 141,
      gold `kb_verdicts.json`, `tune on valid, report test ONCE`
- [ ] 4. Результаты: `7/7` tests, `no-lsp vs lsp` table,
      `top-1 / macro recall / N-recall`, 2–3 examples
      (`ptr::read p1 → Y`, `Box::from_raw p1 → N`)
- [ ] 5. Ограничения + NIRM 4 handoff (ML + GNN + MIR/borrowck)

## Phase 4 — Публикация предварительных результатов [5-7 days, overlaps]

- [ ] 4-page outline for `TSARKA SCIENCE (25.11–01.02)` /
      `AITU DIGITAL GENERATION` slot (plan §5)
- [ ] Sections: Intro / Analyzer / Data+Protocol / Preliminary results / Limitations
- [ ] **No synthetic-measured numbers** (per `synthetic_data_theory.md`);
      only frozen-test numbers

## Definition of Done for НИРМ 3

1. `make_splits.py --check → OK x3`
2. `test_detect.py → 7/7`
3. `eval_protocol.py --retrieval-preds` run on the 97-file test,
   table in report
4. `notes/nirm3_report.md` exists
5. Preliminary paper outline exists

## Commands cheat-sheet

```bash
export PATH=~/.local/bin:$PATH
cd research

# 1. sanity: tests + freeze
python detect/test_detect.py
python synth/splits/make_splits.py --check

# 2. approbation runs (97 frozen test files; test.txt paths are
#    relative to vendors/SafeNet/testdata/; 6 paths contain spaces,
#    hence null-delimited xargs — do NOT word-split them)
T=synth/splits/test.txt
sed "s|^|../vendors/SafeNet/testdata/|" $T | tr '\n' '\0' \
  | xargs -0 python detect/detect.py --no-lsp --json /tmp/nirm3_no_lsp.json
sed "s|^|../vendors/SafeNet/testdata/|" $T | tr '\n' '\0' \
  | xargs -0 python detect/detect.py --json /tmp/nirm3_lsp.json

# 3. audit + score (preds.json built from the LSP report:
#    {"id": "<rel_path e.g. Box::from_raw/1-2.rs>", "pattern_id": N})
python synth/splits/eval_protocol.py
python synth/splits/eval_protocol.py --retrieval-preds /tmp/preds.json
```
