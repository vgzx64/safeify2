# Notes

Working notes for the dissertation and the SafeNet experiments.

## Status legend

- **Active** — current source of truth; update it when the underlying work changes.
- **Historical / archived** — retained for provenance only; do not cite as current.
- **Provisional** — produced before a freeze/commit; must be re-run before being
  treated as a result.
- **Draft** — a proposed design; not a protocol until its freeze gates are met.

## Notes index

| Note | Status | Scope |
|---|---|---|
| [nirm3/README.md](nirm3/README.md) | Active | NIRM 3 scope, Definition of Done, readiness blockers, next actions |
| [nirm3/results.md](nirm3/results.md) | Provisional | Frozen-split protocol, current rerun, superseded history, limitations |
| [research/research-vectors.md](research/research-vectors.md) | Active | Research directions beyond the SafeNet baseline |
| [research/synthetic-data-theory.md](research/synthetic-data-theory.md) | Active | Why and how to build synthetic data without a circular evaluation |
| [research/gnn-coder-evaluation.md](research/gnn-coder-evaluation.md) | Historical | 2026-09-22 evaluation of GNN-Coder as a research candidate |
| [research/transition-dataset.md](research/transition-dataset.md) | Draft | Classification/retrieval dataset: labels, splits, gates |
| [research/transition-dataset-pilot.md](research/transition-dataset-pilot.md) | Draft | v0.2 draft: 435 rows; 607 adjudicated; 110 positive / 325 negative families; all five gates pass; not frozen |

## Archive

[archive/README.md](archive/README.md) lists superseded documents. Archive files
are read-only and are not authoritative.

## Conventions

- One fact lives in one canonical note; other notes link to it.
- Put a status/date line at the top when a note can go stale.
- Use repository-relative artifact paths, not `/tmp`.
- Do not present synthetic-only measurements as results.
- Keep the formal task and deadlines in
  [papers/my_dissertation_plan.md](../papers/my_dissertation_plan.md); notes may
  quote them but must not silently re-scope them.
