# Notes

Working notes for the dissertation and the SafeNet experiments.

## Status legend

- **Active** — current source of truth; update it when the underlying work changes.
- **Historical / archived** — retained for provenance only; do not cite as current.
- **Provisional** — produced before a freeze/commit; must be re-run before being
  treated as a result.
- **Draft** — a proposed design; not a protocol until its freeze gates are met.
- **Planned** — an agreed next step or approach; no implementation/results yet.

## Notes index

| Note | Status | Scope |
|---|---|---|
| [nirm3/README.md](nirm3/README.md) | Active | NIRM 3 scope, Definition of Done, readiness blockers, next actions |
| [nirm3/report.md](nirm3/report.md) | Draft | Supervisor report: scope, protocol, 2026-11-18 post-fix results, safety claim, NIRM 4 handoff |
| [nirm3/signoff-request.md](nirm3/signoff-request.md) | Draft | Three decisions requested from the supervisor (re-scope, test reuse, DoD #3 substitution) |
| [nirm3/results.md](nirm3/results.md) | Provisional | Frozen-split protocol, 2026-11-18 post-fix rerun, per-class/CIs, superseded history, limitations |
| [research/counterexamples.md](research/counterexamples.md) | Active | Safe-Rust counterexample lints (ASEW '24): rules, provenance lattice, threat model, corpus pilot, limitations |
| [research/engine.md](research/engine.md) | Active | Semantic engine: rust-analyzer as a library, resolved rules, interprocedural summaries, parity migration |
| [research/bert-pair-model.md](research/bert-pair-model.md) | Planned | Pair model (BERT/retrieval line; not NIRM 4): state, frozen-BERT cache plan, gates |
| [research/pair-dataset.md](research/pair-dataset.md) | Active | Pair dataset (separate line; not NIRM 4): sources, construction gates, frozen split, final sizes |
| [research/research-vectors.md](research/research-vectors.md) | Active | Research directions beyond the SafeNet baseline |
| [research/synthetic-data-theory.md](research/synthetic-data-theory.md) | Active | Why and how to build synthetic data without a circular evaluation |
| [research/gnn-coder-evaluation.md](research/gnn-coder-evaluation.md) | Historical | 2026-09-22 evaluation of GNN-Coder as a research candidate |
| [research/transition-dataset.md](research/transition-dataset.md) | Active | Classification/retrieval dataset plan; `transitions-core` v0.2 frozen |
| [research/transition-dataset-pilot.md](research/transition-dataset-pilot.md) | Frozen | v0.2 frozen: 433 rows; 8 gates pass; leakage 0; binary target verified (kappa 0.82); M/N not reproducible; one-sided model does not transfer |

## Historical material

Historical snapshots have been removed from the working tree because git history
preserves them. Only canonical active, frozen, or draft documents remain here.

## Conventions

- One fact lives in one canonical note; other notes link to it.
- Put a status/date line at the top when a note can go stale.
- Use repository-relative artifact paths, not `/tmp`.
- Do not present synthetic-only measurements as results.
- Keep the formal task and deadlines in
  [papers/my_dissertation_plan.md](../papers/my_dissertation_plan.md); notes may
  quote them but must not silently re-scope them.

## Project layout

- [`safeify-ai/`](../safeify-ai/README.md) — replaceability judgments
- [`safeify-lint/`](../safeify-lint/README.md) — safe-Rust counterexample lints
- [`safeify-data/`](../safeify-data/README.md) — mining and dataset work
- [`experiments/gnn/`](../experiments/gnn/README.md) — non-production GNN experiment
