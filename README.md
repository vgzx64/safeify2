# safeify2 — SafeNet research workspace

Research workspace for detecting replaceable `unsafe` Rust code and supporting
SafeNet-style recommendation, built around the SafeNet corpus and a frozen
real-data evaluation split.

## Start here

| Area | Entry point | What it contains |
|---|---|---|
| Documentation index | [notes/README.md](notes/README.md) | Active notes, research background, archive policy |
| Current milestone | [notes/nirm3/README.md](notes/nirm3/README.md) | NIRM 3 status, scope, Definition of Done, blockers |
| Current results | [notes/nirm3/results.md](notes/nirm3/results.md) | Frozen-split protocol, reproducible numbers, limitations |
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

**NIRM 3 is in progress and is not ready for supervisor sign-off.** The
detector runs end-to-end and its test suite passes, but the documented v3
results do not reproduce on the current tree, the current run has a nonzero
`FP-on-N`, the test split has been reused, and the report/publication
deliverables do not exist yet. See
[notes/nirm3/README.md](notes/nirm3/README.md) for the blocker list and next
actions.

## Ground rules

- Report only real, held-out data as evidence; synthetic data is augmentation.
- Verify a frozen split with `make_splits.py --check` before every experiment.
- Do not tune on the test split; use `valid` for selection.
- Keep one canonical document per topic; archive superseded notes instead of
  leaving contradictory active pages.
