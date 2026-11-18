# GNN-Coder prototype for SafeNet

> **Status: experimental · Updated: 2026-11-18**
>
> This is a standalone prototype. It is **not integrated** into SafeNet's
> training pipeline, has no measured improvement, and should not be described as
> a drop-in replacement until that integration is done and evaluated.
>
> It is a **post-baseline** augmentation: the first pair-model baseline is the
> frozen-BERT cache + pair head in
> [notes/research/bert-pair-model.md](../../notes/research/bert-pair-model.md).
> Do not use the GNN prototype to skip that baseline.

## Overview

The prototype adds AST graph structure to SafeNet's BERT-based representation.
It targets SafeNet's known loss of hierarchy when an AST is flattened to a
preorder sequence.

The original SafeNet path:

```text
AST → preorder sequence → BERT → SNN → similarity
```

The prototype path:

```text
AST → graph → GNN encoder → fusion → BERT → SNN → similarity
                  │
                  └── child-node-aware pooling
```

## Status

| Item | State |
|---|---|
| Graph converter, GNN encoder, fusion model | Implemented in this directory |
| `GNNOnlyEncoder` / BERT-only ablation switches | Implemented |
| Test suite | Passes locally (see **Testing**) |
| SafeNet training integration | **Not done** |
| Measured improvement over BERT-only | **None yet** |
| `ast_to_graph.py` batch CLI | Legacy; not wired to this checkout |

## Components

1. **Graph converter** — `graph_converter.py`
   - Converts SafeNet's parenthesized simplified-AST format to a graph.
   - Produces node features (59 node-type slots), parent–child edges, and
     child-count importance for pooling.

2. **AST GNN encoder** — `ast_gnn.py`
   - `ChildNodeAwarePooling`: weights nodes by child count.
   - `ASTGNNEncoder`: multi-layer GCN with residual connections.
   - `ASTGNN`: complete graph encoder with a similarity helper.

3. **GNN + transformer fusion** — `gnn_encoder.py`
   - `GNNTransformerFusion`: `concat`, `gate`, or `add` fusion.
   - `CombinedGNNBERT`: GNN + BERT model.
   - `GNNOnlyEncoder`: ablation model.

## Usage

The supported interface is the Python API, run from `research/` so that the
`gnn` package is importable:

```python
from gnn.gnn_encoder import CombinedGNNBERT
from gnn.graph_converter import Code2Graph

converter = Code2Graph()
graph1 = converter.convert(simplified_ast_1)
graph2 = converter.convert(simplified_ast_2)

model = CombinedGNNBERT(
    bert_model=bert,
    use_gnn=True,       # False for the BERT-only ablation
    gnn_in=59,
    gnn_hid=128,
    gnn_out=64,
    gnn_layers=2,
    fusion_dim=128,
    final_dim=32,
    fusion_method="concat",  # "concat", "gate", or "add"
)

emb1, emb2 = model(
    input_ids_1, attention_mask_1,
    input_ids_2, attention_mask_2,
    graph1=graph1,
    graph2=graph2,
)
```

`ast_to_graph.py` is retained for provenance but expects the original
`model.code.gnn` package layout; do not present it as a supported command in
this checkout.

## Testing

From the repository root:

```bash
source .venv/bin/activate
cd research
python -m gnn.test_gnn
```

The suite covers graph conversion, the GNN encoder, the combined model, and the
BERT-only ablation. Optional BERT checks require `torch` and `transformers`;
they are skipped if those imports fail.

## Configuration

### Fusion methods

- `concat` — concatenate GNN and BERT embeddings, then project (default).
- `gate` — learn a weighting between the two embeddings.
- `add` — project both to the same dimension and add.

### Ablation

```python
model = CombinedGNNBERT(bert_model=bert, use_gnn=False)
```

This is the BERT-only control; it does not use graph inputs.

## Performance notes

- GNN parameters are small compared with BERT.
- Graph construction is lightweight and can be cached.
- The prototype was not benchmarked for training or inference cost; the
  `+10–20%` figures in older notes are estimates, not measurements.

## Known gaps

- No SafeNet `bert_cos.py`/`SentencePairDataset` integration.
- No Rust-specific edges (ownership, borrowing, lifetimes).
- No measured comparison against the BERT-only baseline.
- `ast_to_graph.py` has a stale import and is not part of the verified path.
- Older implementation notes are kept in the
  [archive](../../notes/archive/README.md).

## References

- Ye, Y., Pang, P., Zhang, T., & Huang, H. (2025). *GNN-Coder: Boosting
  Semantic Code Retrieval with Combined GNNs and Transformer.*
  arXiv:2502.15202.
- Dong, Y., Zhang, Z., Cui, M., & Xu, H. (2024). *SafeNet: Towards mitigating
  replaceable unsafe Rust code via a recommendation-based approach.* STVR,
  34(5), e1875.

## Related documents

- [Research rationale](../../notes/research/gnn-coder-evaluation.md)
- [Research vectors](../../notes/research/research-vectors.md)
- [Research index](../README.md)
