# GNN-Coder Implementation for SafeNet

> **ARCHIVED — historical only.** Superseded by
> [research/gnn/README.md](../../../research/gnn/README.md). Paths in this file
> describe an old `src/model/code/gnn` layout and are not valid in this
> checkout.

## Summary

Successfully implemented GNN-Coder integration (Ye et al., 2025) for SafeNet to enhance code similarity detection by leveraging AST graph structure.

## Files Created/Modified

### New Files

1. **src/model/code/gnn/__init__.py**
   - Package initialization

2. **src/model/code/gnn/graph_converter.py**
   - AST to graph conversion (Code2Graph)
   - Node type vocabulary (59 types)
   - Graph statistics and JSON serialization

3. **src/model/code/gnn/ast_gnn.py**
   - ChildNodeAwarePooling: GNN-Coder's innovative pooling
   - ASTGNNEncoder: Multi-layer GCN encoder
   - ASTGNN: Complete GNN model for code similarity

4. **src/model/code/gnn/gnn_encoder.py**
   - GNNTransformerFusion: Embedding fusion module
   - CombinedGNNBERT: Full GNN + BERT model
   - GNNOnlyEncoder: Ablation model

5. **src/model/code/gnn/test_gnn.py**
   - Test suite for all components
   - Tests graph conversion, GNN encoder, combined model, BERT-only mode

6. **src/model/code/gnn/README.md**
   - Detailed documentation

7. **src/process/rust_asttree-json/ast_to_graph.py**
   - CLI tool for batch converting AST files to graphs

### Modified Files

1. **vendors/SafeNet/README.md**
   - Added GNN-Coder integration documentation

## Architecture

```
Original SafeNet:  AST → Preorder Traversal → BERT → SNN
Enhanced SafeNet:  AST → Graph → GNN → Fusion → BERT → SNN
```

### Data Flow

1. Simplified AST → Graph Converter → Graph (nodes, edges, node_importance)
2. Graph → GNN Encoder → Graph embedding
3. Graph embedding + BERT embedding → Fusion → Combined embedding
4. Combined embedding → Siamese network → Similarity score

## Key Features

1. **Child-Node-Aware Pooling**
   - GNN-Coder's innovative pooling method
   - Uses child count to weight node importance
   - Highlights topological relationships in AST

2. **Multiple Fusion Methods**
   - concat (default): Concatenate and project
   - gate: Learn gating mechanism
   - add: Project and add

3. **Ablation Support**
   - BERT-only mode (use_gnn=False)
   - Enables comparison of GNN contribution

4. **Drop-in Replacement**
   - CombinedGNNBERT compatible with existing SafeNet pipeline
   - Same interface as XFBert for siamese training

## Testing

All tests pass:
```bash
cd vendors/SafeNet/src/model/code
python -m gnn.test_gnn
```

Output:
- Graph converter: ✓ (2 tests)
- GNN encoder: ✓ (shape, norm, similarity)
- Combined model: ✓ (GNN + BERT)
- BERT-only mode: ✓ (ablation)

## Usage Examples

### Convert AST to Graph
```bash
cd src/process/rust_asttree-json
python ast_to_graph.py ../../data/simplified_ast ../../data/graphs
```

### Use in Training
```python
from gnn.gnn_encoder import CombinedGNNBERT
from gnn.graph_converter import Code2Graph

model = CombinedGNNBERT(bert_model=bert, use_gnn=True)
converter = Code2Graph()
graph = converter.convert(simplified_ast)
emb1, emb2 = model(ids1, mask1, ids2, mask2, graph1=graph, graph2=graph)
```

## Next Steps

1. **Integrate with SafeNet training pipeline**
   - Modify bert_cos.py to use CombinedGNNBERT
   - Add graph data loading to SentencePairDataset

2. **Train and evaluate**
   - Train with GNN enabled
   - Compare with BERT-only baseline
   - Measure improvement on pattern recognition task

3. **Hyperparameter tuning**
   - GNN layers (1-3)
   - GNN hidden dimension (64-256)
   - Fusion method (concat/gate/add)
   - Fusion dimension

4. **Extend node features**
   - Add token value embeddings for leaf nodes
   - Add Rust-specific node types
   - Incorporate dataflow information as edge features

## References

- Ye, Y., Pang, P., Zhang, T., & Huang, H. (2025). "GNN-Coder: Boosting Semantic Code Retrieval with Combined GNNs and Transformer." arXiv:2502.15202.
- Dong, Y., Zhang, Z., Cui, M., & Xu, H. (2024). "SafeNet: Towards mitigating replaceable unsafe Rust code via a recommendation-based approach." STVR, 34(5), e1875.
