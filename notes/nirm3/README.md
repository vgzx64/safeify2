# NIRM 3 (НИРМ 3) — status and plan

> **Status: active · Updated: 2026-11-18 (post-fix) · Readiness: report ready
> pending sign-off; paper not started**
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

The internal decision was to treat the semantic linter (now `safeify-lint/`) as an accepted
`rust-analyzer`-based alternative and defer full MIR/borrowck to NIRM 4. That
decision is documented in [report.md §2](report.md#2-scope-decision-requires-supervisor-approval)
but is **not yet approved by the supervisor**, and NIRM 4's formal scope is ML
models, not MIR. MIR currently has no owning milestone. Do not present the
re-scope as settled until it is accepted in writing.

## Scope extension: safe-Rust counterexamples (2026-11-19)

The formal task text is "базовый статический анализатор", so the milestone can
carry more than the AST/MIR wording. A second, independent front end is
prototyped: lints for the safe-Rust attack patterns of Hassnain & Stanford,
"Counterexamples in Safe Rust" (ASEW '24) — filesystem access through
`/proc/*/mem`-style paths, `Command::new` PATH resolution, `build.rs` writes
outside `OUT_DIR`, dangerous environment variables.

It shares `rust-analyzer` (as a library) with this detector and **none** of the
Y/M/N model: it is not scored on the frozen split, adds no number to
[results.md](results.md), and does not touch the replaceability claim. Design,
threat model, corpus measurement and precision audit:
[counterexamples.md](../research/counterexamples.md). Checks:
`./safeify-lint/cargo.sh test --release` → **8 tests**, including the two
advisory shapes (RUSTSEC-2021-0071 covered by the field-summary rule,
RUSTSEC-2022-0042 by `exec_written_path`, RUSTSEC-2022-0058 out of scope);
`safeify-ai/test_detect.py` → **4/4** (the detector consumes
`safeify-lint --inventory`).

The 2026-11-19 text-engine checks (39/39 Python unit cases, 3/3 advisory
fixtures) are historical: those Python suites were retired with the text
engine. While building the lints, two defects in the old text inventory were
found and fixed: literal-only call arguments were dropped from `arg_spans`, and
`b"…"` byte literals blanked the rest of the line. Neither affected the frozen
split (0 byte string literals in all 288/69/97 files).

## Deliverables and Definition of Done

The formal Definition of Done, with current status:

| # | Requirement | Status |
|---|---|---|
| 1 | `make_splits.py --check` → `OK` three times | ✅ pass |
| 2 | `test_detect.py` → `7/7` | ✅ pass **8/8** 2026-11-18 with pinned RA 0.3.3025; the extra test pins the `ptr::read` p2 rule (LSP path timing-sensitive; see [report §7](report.md#7-failure-analysis)) |
| 3 | `eval_protocol.py --retrieval-preds` run on the 97-file test, table in report | ✅ run 2026-11-18 via exported `pattern_hint` (top-1 0.0928); substitution, not a retrieval model — see [report §5.3](report.md#53-dod-3-retrieval-on-the-frozen-test-split) |
| 4 | `notes/nirm3/report.md` exists | ✅ post-fix draft 2026-11-18 |
| 5 | Preliminary paper outline exists | ❌ not started |

Two additional readiness conditions are not in the original DoD:

- **Frozen provenance.** The detector fix and evaluation artifacts are
  committed at `00f83e9`; the earlier data/report snapshot is `303e12d`; the
  unrelated transitions work is committed at `66e8dcf`. The tree is clean.
  See [report.md](report.md).
- **Safety invariant.** `FP-on-N` is now `0/27` in both modes on this run, but
  the claim is scoped to the frozen split, run and pinned toolchain — not to
  unseen code. See [results.md](results.md) and [report §8](report.md#8-safety-claim).

## Phase status

| Phase | Work | Status |
|---|---|---|
| 0 | Environment repair, frozen split, LSP test | ✅ done 2026-10-19; RA pin restored 2026-11-18; committed `303e12d` |
| 1 | First detector runs on the frozen test split | ✅ done; numbers superseded |
| 2 | Failure analysis and verdict-engine fixes | ✅ analysis done; archived v3 numbers stale |
| 3 | Supervisor report | 🟡 post-fix draft 2026-11-18; needs sign-off |
| 4 | Preliminary paper | ❌ not started (outline due for the 25.11 slot) |

## Readiness blockers

1. **The test split has been reused.** v1 → v2 → v3 bug fixes were chosen after
   inspecting test outcomes, so “report test once” and “nothing tuned on test”
   are not accurate. Either create a fresh holdout or disclose the reuse and do
   selection on `valid`. The report discloses it; the disclosure is not yet
   accepted.
2. **The headline metric is misleading.** 3-way accuracy (`0.2000`) is below a
   constant-`Y` predictor (`0.657`) and `83.81%` of sinks are abstentions. The
   per-class/coverage/risk–coverage/intervals are now in
   [results.md](results.md); do not headline accuracy.
3. **Verdicts move between runs.** Six `from_raw`/`CStr` sinks changed between
   the `303e12d` and `00f83e9` runs with no code change; the cause is
   `rust-analyzer` hover/readiness timeouts, and the effect is confined to the
   raw-pointer-evidence family (±6 sinks). See [report §7.6](report.md#7-failure-analysis).
   Evidence caching, or failing loudly on a readiness timeout, is the fix.
4. **The paper does not exist.** The outline is due for the 25.11 venue slot.
5. **DoD #3 is a substitution.** `--retrieval-preds` is fed the detector's
   `pattern_hint`, not a retrieval model; the supervisor must accept that or
   move retrieval to NIRM 4.
6. **The AST/MIR scope is unapproved.** The re-scope is documented in
   [report.md § 2](report.md#2-scope-decision-requires-supervisor-approval) but
   not accepted, and MIR still has no owning milestone.

~~The `ptr::read` `owner_shaped` false positive~~ is fixed at `00f83e9`
(`FP-on-N` 2/27 → 0/27 in both modes, regression test added).

## Next actions

1. ~~Freeze the tree and record the revision SHA~~ — done: detector/artifacts at
   `00f83e9`, data snapshot at `303e12d`, transitions at `66e8dcf`; tree clean.
2. ~~Fix the `ptr::read` `owner_shaped` false positive using `valid` only, with a
   regression test~~ — done 2026-11-18.
3. ~~Re-run the frozen test split after the fix and score it~~ — done
   2026-11-18; numbers in [report.md](report.md) and [results.md](results.md).
4. ~~Run DoD #3 (`--retrieval-preds`)~~ — done via
   `safeify-ai/export_retrieval.py`; table in [report §5.3](report.md#53-dod-3-retrieval-on-the-frozen-test-split).
5. Decide explicitly whether to carve a fresh holdout or accept the disclosed
   test reuse.
6. Get supervisor sign-off on the report, the AST/MIR re-scope, and the DoD #3
   substitution; the request is drafted in
   [signoff-request.md](signoff-request.md).
7. Produce the 4-page paper outline for the 25.11 venue slot.
8. Pair model (separate from NIRM 4): choose a BERT checkpoint/tokenizer
   recipe and execute the frozen-BERT cache + pair-head baseline; see
   [bert-pair-model.md](../research/bert-pair-model.md). The pair-training CSVs
   are leakage-gated.

## Commands

Sanity checks before any run (workspace-pinned RA; see
[safeify-ai/README.md](../../safeify-ai/README.md)):

```bash
export PATH="$PWD/.tools/ra-bin:$PATH"
export HOME="$PWD/.tools/ra-home"
export RUSTUP_HOME=/home/user/.rustup CARGO_HOME=/home/user/.cargo
source .venv/bin/activate
python safeify-ai/test_detect.py                  # 4/4
python safeify-data/synth/splits/make_splits.py --check
python safeify-data/synth/splits/check_train_leakage.py
```

Full frozen-test and scoring commands are kept in one place:
[report.md § 9](report.md#9-reproducibility) and
[results.md § Reproduce](results.md#reproduce).

## Documentation

- [Supervisor report (current)](report.md)
- [Results and protocol](results.md)
- Archived NIRM 3 notes: removed in the 2026-11-20 reorganisation; Git history preserves them
- [Research vectors](../research/research-vectors.md)
- [Synthetic-data theory](../research/synthetic-data-theory.md)
- [Formal dissertation plan](../../papers/my_dissertation_plan.md)
