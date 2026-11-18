# NIRM 3 — sign-off request

> **Status: draft to send · 2026-11-18**
>
> Attach or link [report.md](report.md) and [results.md](results.md).
> This note lists the three decisions the report needs, plus two smaller
> confirmations. It is written to be sent as-is.

## Where NIRM 3 stands

The detector, frozen protocol and evaluation are done; the report is a
post-fix draft. Current LSP numbers on the frozen 97-file test split (105
evaluated sinks, run `00f83e9`):

| Metric | Value |
|---|---:|
| Accuracy | 0.2000 (21/105) |
| `FP-on-N` (gold N → pred Y) | **0/27** |
| `recall_N` | 0.3704 (10/27) |
| Decisive claims / correct | 17 / 12 |
| Abstention rate | 83.81% |
| Macro-F1 (95% CI) | 0.2394 [0.1583, 0.3923] |

What we do **not** claim: that the analyzer is a safety oracle, that accuracy
beats a constant predictor (it does not: constant-`Y` scores 0.657), or that
these numbers come from a clean holdout.

## Decision 1 — AST/MIR re-scope

The formal task says “AST and MIR analyzer”. The delivered system is a
source-level `unsafe` inventory with `rust-analyzer` hover/type evidence: no AST
traversal, no MIR, no borrowck. The deviation and its consequences are in
[report.md §2](report.md#2-scope-decision-requires-supervisor-approval).

**Requested:** either (a) approve the `rust-analyzer`-based alternative as the
NIRM 3 deliverable, or (b) require MIR and assign it an owning milestone. NIRM 4
is scoped to ML models, so MIR currently has no owner.

## Decision 2 — test-split reuse

The frozen test split was used across v1 → v2 → v3 fixes and the 2026-10-24 and
2026-11-18 audits, so “report test once” was not honoured. The report discloses
this under every results table ([report.md §4](report.md#4-data-and-evaluation-protocol)).

**Requested:** either (a) accept the disclosed reuse, treating the numbers as an
exploratory upper-bound estimate, or (b) require a fresh holdout. Option (b)
means re-splitting and re-labelling SafeNet testdata and re-running detection —
roughly several days, which does not fit the 22.11 report window; it would move
the clean result past the 25.11 paper slot.

## Decision 3 — DoD #3 retrieval item

The DoD asks for `eval_protocol.py --retrieval-preds` on the test split. The
detector has no retrieval model, so we exported its modal `pattern_hint` per
file (`detect/export_retrieval.py`) and scored that: top-1 pattern accuracy
**0.0928** (LSP), `N`-query recall 5/23 ([report.md §5.3](report.md#53-dod-3-retrieval-on-the-frozen-test-split)).

**Requested:** either (a) accept the `pattern_hint` export as satisfying DoD #3,
with the limitation stated, or (b) keep it open and move retrieval to NIRM 4,
where a real model would be trained.

## Two confirmations

1. **`rust-analyzer` variance.** Six `from_raw`/`CStr` verdicts changed between
   two full runs with no code change (hover/readiness timeouts, ±6 sinks;
   [report.md §7.6](report.md#7-failure-analysis)). Is a run that is stable to
   within a few sinks acceptable for the reported numbers, or should evidence
   caching land before sign-off?
2. **Paper outline.** The 4-page outline targets the 25.11 slot. Please confirm
   the venue/format, or the outline can be written against the report structure
   as-is.

## What is requested in writing

A short reply accepting, rejecting or amending items 1–3 (and the two
confirmations) is enough. The report marks each as pending until then; nothing
in it is presented as settled.
