# NIRM 3 (НИРМ 3) — status and plan

> **Status: active · Updated: 2026-10-24 · Readiness: not ready for sign-off**
>
> Work window: `01.09.2026 – 08.11.2026`
> Report to supervisor: `09.11.2026 – 22.11.2026`

## Formal task

From [papers/my_dissertation_plan.md](../../papers/my_dissertation_plan.md):

> *НИРМ 3. Реализация базового статического анализатора на основе AST и MIR
> компилятора Rust. Апробация анализатора на тестовых наборах данных и
> публикация предварительных результатов.*

## Scope decision

The current implementation is **not** an AST/MIR analyzer. It is a pure-Python
source masker and unsafe-region inventory plus rust-analyzer hover evidence
(`type`/HIR-adjacent) and an optional `rustc --emit=metadata` gate. There is no
direct AST traversal and no MIR.

The internal decision was to treat `research/detect/` as an accepted
`rust-analyzer`-based alternative and defer full MIR/borrowck to NIRM 4. That
decision is **not yet documented in the report or approved by the supervisor**,
and NIRM 4's formal scope is ML models, not MIR. MIR currently has no owning
milestone. Do not present the re-scope as settled until it is accepted in
writing.

## Deliverables and Definition of Done

The formal Definition of Done, with current status:

| # | Requirement | Status |
|---|---|---|
| 1 | `make_splits.py --check` → `OK` three times | ✅ pass |
| 2 | `test_detect.py` → `7/7` | ✅ pass 2026-11-18 with pinned RA 0.3.3025 (LSP path timing-sensitive; see [report §7](report.md#7-failure-analysis)) |
| 3 | `eval_protocol.py --retrieval-preds` run on the 97-file test, table in report | ❌ not run; detector emits `pattern_hint`, not retrieval predictions |
| 4 | `notes/nirm3/report.md` exists | ✅ draft exists 2026-11-18 |
| 5 | Preliminary paper outline exists | ❌ not started |

Two additional readiness conditions are not in the original DoD:

- **Frozen provenance.** `HEAD` is `303e12d` (NIRM 3/detector/data changes
  committed); 42 paths remain dirty, almost all pre-existing
  `research/transitions/` work. See [report.md](report.md).
- **Safety invariant.** The current code produces `FP-on-N`; the archived v3
  claim of `0/27` is no longer true. See [results.md](results.md).

## Phase status

| Phase | Work | Status |
|---|---|---|
| 0 | Environment repair, frozen split, LSP test | ✅ done 2026-10-19; RA pin restored 2026-11-18; committed `303e12d` |
| 1 | First detector runs on the frozen test split | ✅ done; numbers superseded |
| 2 | Failure analysis and verdict-engine fixes | ✅ analysis done; archived v3 numbers stale |
| 3 | Supervisor report | 🟡 draft written 2026-11-18; needs sign-off |
| 4 | Preliminary paper | ❌ not started |

## Readiness blockers

1. **Documented numbers do not reproduce.** The archived v3 note reports
   accuracy `0.162`, `FP-on-N 0/27`, `recall_N 0.296`; the 2026-10-24 rerun gave
   `0.171`, `2/27`, and `0.259`. The 2026-11-18 rerun in
   [report.md](report.md) is now the authoritative result; the archived v1/v2/v3
   numbers are superseded. `verdict.py` changed after the archived note was
   written, and the old raw files are gone.
2. **The safety claim is currently false.** Both LSP and no-LSP modes flag
   `std::ptr::read(&self.entries[i])` in
   [ptr::read/2-1.rs](../../vendors/SafeNet/testdata/ptr::read/2-1.rs) as `Y`
   although gold is p2 `N`. This is two sink-level false positives in one file
   (1/23 N files).
3. **The test split has been reused.** v1 → v2 → v3 bug fixes were chosen after
   inspecting test outcomes, so “report test once” and “nothing tuned on test”
   are not accurate. Either create a fresh holdout or disclose the reuse and do
   selection on `valid`.
4. **The headline metric is misleading.** 3-way accuracy is below a constant-`Y`
   predictor; `86.7%` of sinks are abstentions. Report per-class
   precision/recall/F1, coverage, risk–coverage, and intervals instead.
5. **The paper does not exist**, and `eval_protocol.py --retrieval-preds` has
   not been run. The report draft is written but not approved.
6. **The repository is not fully clean.** `HEAD` is `303e12d`; 42 paths remain
   dirty, mostly pre-existing `research/transitions/` work. The NIRM 3/detector/
   data files are committed.

## Next actions

1. Freeze the tree: commit the detector, report, data fixes, and generated
   artifacts; record the clean revision SHA and the split/result hashes.
2. Fix the `ptr::read` `owner_shaped` false positive using `valid` only; add a
   regression test for the `ptr::read/2-1.rs` shape.
3. ~~Run the test split once, cleanly~~ — done 2026-11-18; the archived v1/v2/v3
   numbers are marked superseded. Re-run only after the FP fix, and disclose the
   reuse.
4. Decide explicitly whether to carve a fresh holdout or disclose test reuse.
5. Get supervisor sign-off on the report and the AST/MIR re-scope in
   [report.md § 2](report.md#2-scope-decision-requires-supervisor-approval).
6. Produce the 4-page paper outline for the 25.11 venue slot.
7. NIRM 4: choose a BERT checkpoint/tokenizer recipe and a CPU-feasible
   frozen-BERT path; the pair-training CSVs are now leakage-gated.

## Commands

Sanity checks before any run (workspace-pinned RA; see
[detect/README.md](../../research/detect/README.md)):

```bash
export PATH="$PWD/../.tools/ra-bin:$PATH"      # from research/
export HOME="$PWD/../.tools/ra-home"
export RUSTUP_HOME=/home/user/.rustup CARGO_HOME=/home/user/.cargo
cd research && source ../.venv/bin/activate
python detect/test_detect.py                  # 7/7
python synth/splits/make_splits.py --check    # OK
python synth/splits/check_train_leakage.py    # OK
```

Full frozen-test and scoring commands are kept in one place:
[report.md § 9](report.md#9-reproducibility) and
[results.md § Reproduce](results.md#reproduce).

## Documentation

- [Supervisor report (current)](report.md)
- [Results and protocol](results.md)
- [Archived NIRM 3 notes](../archive/README.md)
- [Research vectors](../research/research-vectors.md)
- [Synthetic-data theory](../research/synthetic-data-theory.md)
- [Formal dissertation plan](../../papers/my_dissertation_plan.md)
