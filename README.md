# Safeify

Safeify is a Rust security research workspace organized around two implementation products and supporting data work.

## Products

| Area | Purpose |
|---|---|
| [`safeify-ai/`](safeify-ai/README.md) | Replaceable-unsafe judging: unsafe-region inventory, rust-analyzer evidence, Y/M/N verdicts, evaluation and retrieval exports |
| [`safeify-lint/`](safeify-lint/README.md) | Counterexamples-in-Safe-Rust analysis: semantic filesystem, process, environment and build-script lints |
| [`safeify-data/`](safeify-data/README.md) | Transition mining, CVE/RustSec provenance, synthetic data, split generation and dataset verification |
| [`experiments/gnn/`](experiments/gnn/README.md) | Experimental GNN-Coder/GNN+BERT research; not part of a product or frozen result |

`safeify-ai` consumes `safeify-lint --inventory` for its unsafe-region inventory. The two products have separate outputs: Y/M/N replaceability judgments versus deny/warn/info lint findings.

## Current status

- **safeify-ai:** experimental; its fixed NIRM 3 report is superseded by no final sign-off result.
- **safeify-lint:** rust-analyzer semantic engine implemented and tested.
- **safeify-data:** transition and synthetic datasets exist; the frozen real-data split is available.
- **Pair model:** not trained (separate line; not NIRM 4); see [`notes/research/bert-pair-model.md`](notes/research/bert-pair-model.md).
- **NIRM 4** (ML warning classification for the hybrid system): not started.

## Key documentation

- [`notes/README.md`](notes/README.md) — canonical notes index
- [`notes/nirm3/report.md`](notes/nirm3/report.md) — historical NIRM 3 supervisor report draft
- [`notes/nirm3/results.md`](notes/nirm3/results.md) — NIRM 3 result protocol and caveats
- [`notes/research/counterexamples.md`](notes/research/counterexamples.md) — Safe-Rust counterexample design
- [`notes/research/engine.md`](notes/research/engine.md) — semantic engine documentation
- [`notes/research/bert-pair-model.md`](notes/research/bert-pair-model.md) — planned pair-model work
- [`notes/research/pair-dataset.md`](notes/research/pair-dataset.md) — pair-classification dataset: sources, construction gates, final sizes
- [`papers/my_dissertation_plan.md`](papers/my_dissertation_plan.md) — formal milestones

## Shared inputs

- `vendors/SafeNet/` — upstream corpus and knowledge base
- `vendors/rust-analyzer/` — pinned semantic-analysis implementation
- `rust_ecosystem` — host-specific research checkout/symlink
- `.tools/` — generated rust-analyzer and Cargo tooling

## Ground rules

- Do not present synthetic-only measurements as real held-out results.
- Verify frozen splits before model or evaluation runs.
- Keep product code separate from experiments.
- Keep historical reports and superseded runs in dated artifacts or archives; never present them as current.
