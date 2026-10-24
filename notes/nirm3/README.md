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
| 2 | `test_detect.py` → `7/7` | ✅ pass |
| 3 | `eval_protocol.py --retrieval-preds` run on the 97-file test, table in report | ❌ not run; detector emits `pattern_hint`, not retrieval predictions |
| 4 | `notes/nirm3/report.md` exists | ❌ not started |
| 5 | Preliminary paper outline exists | ❌ not started |

Two additional readiness conditions are not in the original DoD:

- **Frozen provenance.** The repository has no commits yet; the current tree
  cannot be tied to a revision SHA.
- **Safety invariant.** The current code produces `FP-on-N`; the archived v3
  claim of `0/27` is no longer true. See [results.md](results.md).

## Phase status

| Phase | Work | Status |
|---|---|---|
| 0 | Environment repair, frozen split, LSP test | ✅ done 2026-10-19; commit still pending |
| 1 | First detector runs on the frozen test split | ✅ done; numbers superseded |
| 2 | Failure analysis and verdict-engine fixes | ✅ analysis done; archived v3 numbers stale |
| 3 | Supervisor report | ❌ not started |
| 4 | Preliminary paper | ❌ not started |

## Readiness blockers

1. **Documented numbers do not reproduce.** The archived v3 note reports
   accuracy `0.162`, `FP-on-N 0/27`, `recall_N 0.296`; the 2026-10-24 rerun gives
   `0.171`, `2/27`, and `0.259`. `verdict.py` was modified after the note was
   written, and the raw report files are gone.
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
   predictor; `87.6%` of sinks are abstentions. Report per-class
   precision/recall/F1, coverage, risk–coverage, and intervals instead.
5. **The report and paper do not exist**, and `eval_protocol.py
   --retrieval-preds` has not been run.
6. **The repository is uncommitted.** `dev` has no commits; all work is
   untracked.

## Next actions

1. Freeze the tree: commit on `dev`, pin Python/rust-analyzer versions, keep raw
   reports under the repo, record the split/result hashes.
2. Fix the `ptr::read` `owner_shaped` false positive using `valid` only; add a
   regression test for the `ptr::read/2-1.rs` shape.
3. Run the test split once, cleanly; score per-class metrics and baselines; mark
   the archived v1/v2/v3 numbers as superseded.
4. Decide explicitly whether to carve a fresh holdout or disclose test reuse.
5. Write `notes/nirm3/report.md`, including the AST/MIR re-scope and the MIR
   ownership plan; get supervisor sign-off.
6. Produce the 4-page paper outline for the 25.11 venue slot.

## Commands

Sanity checks before any run:

```bash
export PATH="$HOME/.local/bin:$PATH"
cd research && source ../.venv/bin/activate
python detect/test_detect.py
python synth/splits/make_splits.py --check
```

Full frozen-test and scoring commands are kept in one place:
[results.md § Reproduce](results.md#reproduce).

## Documentation

- [Results and protocol](results.md)
- [Archived NIRM 3 notes](../archive/README.md)
- [Research vectors](../research/research-vectors.md)
- [Synthetic-data theory](../research/synthetic-data-theory.md)
- [Formal dissertation plan](../../papers/my_dissertation_plan.md)
