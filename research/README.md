# Research

Experimental implementations that extend or modify the SafeNet baseline. Each
experiment has its own README; this page is only an index.

## Experiments

### `detect/` — replaceable-unsafe detector (NIRM 3)

Pure-Python unsafe-region inventory plus rust-analyzer hover evidence and an
optional `rustc --emit=metadata` gate. Emits `Y/M/N` verdicts with a
`safe_alternative` and an encapsulation hint.

- Entry point: [detect/README.md](detect/README.md)
- Current status and protocol: [notes/nirm3/results.md](../notes/nirm3/results.md)
- **Status:** experimental; no final result claimed.

### `synth/` — deterministic synthetic dataset

Counterfactual injection and template/rule generation for SafeNet-style
training, with rustc verification and a frozen real-data split.

- Entry point: [synth/README.md](synth/README.md)
- Frozen split: [synth/splits/README.md](synth/splits/README.md)
- **Status:** dataset and split tooling usable; strategies C/D are out of scope.

### `gnn/` — GNN-Coder prototype

Experimental AST-to-graph + GNN + BERT fusion prototype based on Ye et al.
(2025). It is **not integrated** into the SafeNet training pipeline and has no
measured improvement yet.

- Entry point: [gnn/README.md](gnn/README.md)
- Research rationale: [notes/research/gnn-coder-evaluation.md](../notes/research/gnn-coder-evaluation.md)
- **Status:** prototype only.

## Shared inputs

- `vendors/SafeNet/` — upstream corpus and knowledge base (git submodule).
- `rust-src-1.99.1.tar.xz`, `rust-src-gnu.tar.xz` — local rust-src archives for
  the rust-analyzer shim.
- `rust_ecosystem` — symlink to a host-specific checkout; not portable across
  machines.

## Documentation

- [notes/README.md](../notes/README.md) — notes index and conventions
- [notes/nirm3/README.md](../notes/nirm3/README.md) — NIRM 3 status and plan
- [papers/my_dissertation_plan.md](../papers/my_dissertation_plan.md) — formal
  milestones and deadlines

## Ground rules

- Research code is experimental; do not treat a prototype as an integrated
  system.
- Evaluate on real, held-out data, not on synthetic-only measurements.
- Run `python synth/splits/make_splits.py --check` before any experiment.
