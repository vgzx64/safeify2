# safeify2 — SafeNet research workspace

Research workspace for detecting replaceable `unsafe` Rust code and supporting
SafeNet-style recommendation, built around the SafeNet corpus and a frozen
real-data evaluation split.

## Start here

| Area | Entry point | What it contains |
|---|---|---|
| Documentation index | [notes/README.md](notes/README.md) | Active notes, research background, archive policy |
| Current milestone | [notes/nirm3/README.md](notes/nirm3/README.md) | NIRM 3 status, scope, Definition of Done, blockers |
| Current report | [notes/nirm3/report.md](notes/nirm3/report.md) | NIRM 3 supervisor report: scope, protocol, 2026-11-18 results, disclosures |
| Current results | [notes/nirm3/results.md](notes/nirm3/results.md) | Frozen-split protocol, current numbers, limitations |
| Pair-model plan | [notes/research/bert-pair-model.md](notes/research/bert-pair-model.md) | NIRM 4 BERT pair model: current state, frozen-BERT cache plan, gates |
| Dataset plan | [notes/research/transition-dataset.md](notes/research/transition-dataset.md) | Classification/retrieval labels, splits, quality gates |
| Experiments | [research/README.md](research/README.md) | `detect/`, `gnn/`, `synth/` and their READMEs |
| Dissertation plan | [papers/my_dissertation_plan.md](papers/my_dissertation_plan.md) | Formal NIRM milestones and deadlines |
| Archive | [notes/archive/README.md](notes/archive/README.md) | Superseded notes, kept for provenance only |

## Repository map

```text
notes/       research notes, milestone status, archived history
research/    detector, GNN prototype, synthetic-data pipeline
papers/      dissertation plan and publication drafts
vendors/     SafeNet submodule (read-only upstream corpus)
```

`research/rust-src-*.tar.xz` and `research/rust_ecosystem` are external
research inputs; the latter is a symlink to a host-specific path and is not
portable across checkouts.

## Current status

**NIRM 3 has a working detector and a post-fix report draft awaiting
supervisor sign-off.** The 2026-11-18 frozen rerun is the current baseline
(8/8 suite with a pinned rust-analyzer; LSP accuracy 0.2000; `FP-on-N` 0/27;
17 decisive claims, 12 correct; 83.81% abstentions). Remaining blockers are
the disclosed reuse of the test split, acceptance of the DoD #3 substitution,
approval of the AST/MIR re-scope, rust-analyzer verdict variance, and the
missing publication. See [notes/nirm3/report.md](notes/nirm3/report.md) and
[the sign-off request](notes/nirm3/signoff-request.md).

The BERT/SafeNet-style pair classifier is **NIRM 4**, not NIRM 3, and no model
has been trained. Its training data was rebuilt on 2026-11-18 so valid/test are
excluded and gated; the first planned approach is a frozen-BERT embedding cache
plus a pair head. See
[notes/research/bert-pair-model.md](notes/research/bert-pair-model.md).

## Ground rules

- Report only real, held-out data as evidence; synthetic data is augmentation.
- Verify a frozen split with `make_splits.py --check` before every experiment.
- Do not tune on the test split; use `valid` for selection.
- Keep one canonical document per topic; archive superseded notes instead of
  leaving contradictory active pages.
