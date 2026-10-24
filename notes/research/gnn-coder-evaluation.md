# GNN-Coder Evaluation for SafeNet Enhancement

> **Status: historical · 2026-09-22 · Decision input, not implementation status.**
> See the [GNN prototype README](../../research/gnn/README.md) for what is
> actually implemented and tested. Current status is prototype-only, not
> integrated, with no measured improvement.

**Candidate:** Ye et al. (2025) - "GNN-Coder: Boosting Semantic Code Retrieval with Combined GNNs and Transformer" (arXiv:2502.15202)

**Date:** 2026-09-22

**Evaluator:** Cline (Solar Pro4)

---

## 1. Executive Summary

**Verdict: PROMISING CANDIDATE — Worth prototyping, but with caveats**

GNN-Coder directly addresses the core weakness in SafeNet's architecture: the flattening of AST to a preorder traversal sequence. It demonstrates consistent improvements (1-10% MRR on CSN, 20% zero-shot on CosQA) by combining GNN-based AST structure learning with Transformer representations. However, it was designed for **code retrieval** (NL→code), not **code similarity/pattern matching**, so adaptation is required. The graph pooling innovation is particularly relevant to SafeNet's pattern disambiguation task.

**Recommendation:** Prototype a GNN-augmented embedding pipeline as a drop-in replacement for SafeNet's AST→BERT→SNN path, starting with a simplified integration before attempting full GNN-Coder replication.

---

## 2. What GNN-Coder Actually Does

### 2.1 High-Level Architecture

```
Raw Code → Tree-sitter AST → Code2Graph (prune + add edges) → GNN Encoding 
                                                                     ↓
                                                            Graph Pooling (child-node-aware)
                                                                     ↓
                                                            Node Embeddings
                                                                     ↓
                                                            + Transformer (CodeBERT/UniXcoder)
                                                                     ↓
                                                            Fused Representation
                                                                     ↓
                                                            Cosine Similarity / Retrieval
```

### 2.2 Code2Graph: AST to Graph Transformation

**Parsing:** Uses Tree-sitter to parse code into AST.

**Pruning (shadow node removal):**
- Standard ASTs contain redundant/intermediate nodes (e.g., decorative syntax nodes)
- GNN-Coder prunes these to get a "refined AST graph"
- Retains semantically meaningful nodes: operators, identifiers, literals, keywords, function calls, etc.

**Graph construction:**
- **Nodes:** Retained AST nodes, each with:
  - Node type encoding (one-hot or learned embedding of AST node type)
  - Token feature (if leaf node: the actual token text embedded)
- **Edges:** Two types added:
  1. **Original AST parent-child edges** (preserving hierarchy)
  2. **Additional semantic edges** (likely data-flow or control-flow related, exact types need verification from paper)

**Key insight:** This preserves the tree structure that SafeNet's preorder flattening loses, while making it amenable to GNN message passing.

### 2.3 GNN Architecture

Based on the description, GNN-Coder uses a standard GNN stack:

- **Layer type:** Likely GCN (Graph Convolutional Network) or similar message-passing GNN (exact type not fully specified in excerpts, but the paper mentions "message passing")
- **Layers:** Multiple GNN layers for neighborhood aggregation
- **Node update:** Each node's representation is updated by aggregating information from its neighbors
- **Output:** Per-node embeddings that encode both local structure and token information

### 2.4 Graph Pooling: The Key Innovation

This is GNN-Coder's main technical contribution and most relevant to SafeNet.

**Problem:** Standard graph pooling (mean, max, sum, or learned pooling like DiffPool/SortPool) treats all nodes equally or uses generic criteria. For ASTs, not all nodes are equally important.

**GNN-Coder solution:** Pooling method that uses **number of child nodes** as a key feature.

**Intuition:**
- Nodes with many children are likely "structural" nodes (e.g., function definitions, block statements) that organize code
- Nodes with few/no children are likely "leaf" nodes (identifiers, literals)
- Weighting by child count highlights the topological importance of nodes

**Result:** More discriminative graph-level representations that better preserve AST topology.

**Ablation:** Tested pooling ratios (0.1, 0.3, 0.5, 0.7, 0.9) — found optimal varies by model and dataset, with 0.3-0.5 generally good.

### 2.5 Transformer Fusion

The GNN output (graph-level embedding from pooling) is combined with Transformer embeddings:

- **Base Transformer:** CodeBERT, UniXcoder, or CodeT5+ (pretrained code models)
- **Fusion mechanism:** Concatenation or addition of GNN embedding with transformer output
- **Effect:** Combines sequential/token understanding (Transformer) with structural understanding (GNN)

### 2.6 Training and Results

**Datasets:**
- **CSN (CodeSearchNet):** 6 languages (Ruby, JavaScript, Go, Python, Java, PHP) — code retrieval task
- **CosQA:** Question-answering based code search — zero-shot transfer

**Key Results (MRR improvements from adding GNN):**

| Model | Improvement Range |
|-------|------------------|
| UniXcoder + GNN-Coder | 1-10% MRR on CSN |
| CodeT5+ + GNN-Coder | 1-10% MRR on CSN |
| Zero-shot on CosQA | ~20% gain |

**Notable:** Improvements are larger on "structurally complex" code fragments, which is exactly SafeNet's target (unsafe code patterns can be structurally intricate).

**MAM metric:** Lower Mean Angular Margin after GNN addition = more separable, discriminative embeddings. This directly benefits SafeNet's pattern discrimination.

---

## 3. Fit Assessment for SafeNet

### 3.1 Where GNN-Coder Helps SafeNet

| SafeNet Weakness | GNN-Coder Solution | Impact |
|-----------------|-------------------|--------|
| AST flattened to preorder sequence | Code2Graph preserves AST hierarchy as graph | **High** — structural info retained |
| Multiple trees can share same preorder traversal | GNN sees actual tree topology | **High** — disambiguation improved |
| Pattern recognition needs structural understanding | GNN learns structural patterns via message passing | **Medium-High** |
| Embeddings need to be discriminative | Child-node-aware pooling creates better graph reps | **Medium** |
| "BERT may be influenced by non-code information" | GNN adds purely structural signal | **Medium** |

### 3.2 Where Adaptation Is Needed

| Aspect | GNN-Coder Default | SafeNet Need | Adaptation Required |
|--------|-----------------|-------------|---------------------|
| **Task** | NL→Code retrieval | Code→Code similarity/pattern matching | Change input: both sides are code, not NL+code |
| **Input** | Code + NL query | Two code snippets (query + knowledge base) | Both encoded through same GNN+Transformer pipeline |
| **Model backbone** | CodeBERT/UniXcoder/CodeT5+ | BERT (fine-tuned on Rust) | Could use Rust-finetuned CodeBERT or similar |
| **Pooling output** | Single graph embedding for retrieval | Need embedding for similarity comparison | Same pooling works; just use for both code snippets |
| **Edge types** | Designed for general code | Rust-specific semantics (ownership, borrowing) | Could add Rust-specific edge types (borrow edges, ownership edges) |
| **Language** | Multi-language (6 languages) | Rust-only | Can still use multi-language pretraining; fine-tune on Rust |

### 3.3 Potential Synergy with SafeNet's Existing Components

1. **Dataflow filter (Rust side):** GNN-Coder's graph structure could be enriched with SafeNet's dataflow analysis results as edge features or node annotations. This would combine the best of both: static analysis precision + learned structural patterns.

2. **Existing AST pipeline (Rust side):** SafeNet already extracts Rust AST via `syn` crate. The `astsimpletree.py` and `simplifyast.py` scripts could be extended to produce graph format instead of flattened sequence. This is a natural evolution of existing infrastructure.

3. **Siamese network (Python side):** The SNN architecture in `bert_cos.py` would remain largely unchanged — it just receives better embeddings from the GNN-augmented encoder.

---

## 4. Implementation Complexity Assessment

### 4.1 Minimal Viable Integration (Low Risk)

**Goal:** Replace SafeNet's AST→preorder→BERT path with AST→graph→GNN→BERT path, keeping everything else the same.

**Changes needed:**
1. **Rust side:** Modify `astsimpletree.py` to output graph format (edge list + node features) instead of preorder sequence. Relatively straightforward since the simplified AST is already a tree.
2. **Python side:** Add GNN layer before BERT in `model_utils_bert.py`. Initial approach: simple GCN over the AST graph, pool to graph embedding, concatenate with BERT [CLS] token.
3. **Training:** Same siamese setup, same loss. Let the model learn to use GNN features.

**Effort:** 2-3 weeks for a prototype.

**Risk:** Low. Can fall back to SafeNet baseline if GNN doesn't help.

### 4.2 Full GNN-Coder Replication (Medium Risk)

**Goal:** Replicate GNN-Coder's complete pipeline adapted for Rust unsafe code pattern matching.

**Changes needed:**
1. **Tree-sitter for Rust:** Need a Rust Tree-sitter parser (exists: `tree-sitter-rust`)
2. **Code2Graph:** Implement pruning and edge addition for Rust AST
3. **GNN stacking:** Proper multi-layer GNN with the child-node-aware pooling
4. **Fusion:** Proper integration with a Rust-aware transformer
5. **Training:** May need to retrain or fine-tune the transformer on Rust code

**Effort:** 6-10 weeks for a solid implementation.

**Risk:** Medium. More complex, but more potential upside.

### 4.3 Enhanced Version (High Effort, High Reward)

**Goal:** Combine GNN-Coder with SafeNet's unique strengths.

**Enhancements:**
1. **Rust-specific edges:** Add borrow checker graph edges, ownership flow edges, lifetime edges to the AST graph
2. **Dataflow as features:** Encode SafeNet's dataflow analysis results as node/edge features
3. **Multi-task:** Jointly predict pattern + replaceability + safety guarantee
4. **Hybrid filtering:** Use GNN embeddings to complement the dataflow filter, not just replace it

**Effort:** 10-16 weeks.

**Risk:** Medium-High. More moving parts, but leverages SafeNet's existing analysis infrastructure in a novel way.

---

## 5. Hardware and Accessibility Assessment

The [research vectors](research-vectors.md) constraint is: *"Maintain inference & training accessible to average consumer hardware"*

**GNN-Coder overhead:**
- GNN layers add some parameters but are generally lightweight compared to transformers
- Graph construction (Code2Graph) adds preprocessing time but is one-time per sample
- Pooling adds minimal compute
- The GNN itself: Even a 2-3 layer GCN with 128-256 hidden dims is small

**Estimated additional training cost:**
- GNN parameters: ~1-5M additional parameters (small compared to BERT's 110M)
- Training time: +10-30% depending on graph size and GNN depth
- Inference: +5-15% latency for graph encoding

**Verdict:** GNN addition is compatible with consumer hardware constraint. The bottleneck remains the transformer, and GNN adds relatively little overhead.

**Caveat:** If using very large GNN (many layers, large hidden dims, complex pooling), overhead grows. Keep GNN lightweight — 2-3 layers, 128-256 dims should suffice for AST graphs which are typically small (hundreds of nodes for typical functions).

---

## 6. Alternatives to Consider

Before committing to GNN-Coder specifically, consider:

### 6.1 Code2Vec / Code2Seq (Alon et al.)

- **Approach:** Learn from paths in the AST (not flatten to sequence, not full GNN)
- **Pros:** Simpler than GNN, proven for code tasks, path-based representation captures structure
- **Cons:** Paths may miss some structural relationships; less expressive than GNN for complex graphs
- **Fit:** Could be a middle ground between SafeNet's flattening and full GNN-Coder

### 6.2 Tree-LSTM / Tree-Transformer

- **Approach:** Architectures designed specifically for tree structures
- **Pros:** Natural fit for ASTs, no graph conversion needed
- **Cons:** Less general than GNN, may not capture cross-branch relationships as well
- **Fit:** Worth evaluating if GNN proves overkill

### 6.3 Structure-Aware BERT Variants

- **Examples:** StructBERT, Absolute Position Encoding with structural info
- **Approach:** Modify BERT's position encoding or input to include structural information
- **Pros:** Minimal architecture change, drop-in upgrade to existing BERT pipeline
- **Cons:** Less expressive than dedicated GNN for structure
- **Fit:** Good quick experiment before committing to full GNN pipeline

### 6.4 PyTorch Geometric (PyG) or DGL for GNN

- **Note:** These are frameworks, not models, but worth mentioning for implementation
- **PyG:** Good for small-medium graphs, easy to use with existing PyTorch code
- **DGL:** More scalable, good for larger graphs
- **Recommendation:** PyG likely sufficient for SafeNet's AST graphs

---

## 7. Recommended Next Steps

### Phase 1: Feasibility Study (1-2 weeks)

1. **Implement minimal Code2Graph** for SafeNet's existing simplified AST format
   - Input: SafeNet's simplified AST (parenthesized tree format)
   - Output: Edge list + node type matrix
   - Goal: Verify that SafeNet's AST can be easily converted to graph format

2. **Prototype GNN encoding** in the existing Python pipeline
   - Add a 2-layer GCN before BERT in `model_utils_bert.py`
   - Pool graph to embedding, concatenate with BERT output
   - Keep everything else identical

3. **Run ablation** on a small subset of SafeNet data
   - Compare: BERT-only vs BERT+GNN
   - Metric: Pattern recognition accuracy on held-out test set
   - Goal: Determine if GNN adds value before full commitment

### Phase 2: If Promising (3-6 weeks)

4. **Implement child-node-aware pooling** from GNN-Coder
5. **Add Rust-specific edge types** (borrow, ownership, lifetime)
6. **try different GNN architectures** (GAT, GraphSAGE) for comparison
7. **Scale up training** to full dataset

### Phase 3: Integration (2-4 weeks)

8. **Integrate with dataflow filter** — use GNN embeddings as additional signal
9. **Optimize for inference speed** — graph construction caching, model quantization if needed
10. **Evaluate on full test set** with all the metrics from [research vectors](research-vectors.md)

---

## 8. Risks and Mitigations

| Risk | Likelihood | Impact | Mitigation |
|------|-----------|--------|------------|
| GNN doesn't improve over flattened AST for this task | Medium | High | Phase 1 ablation will catch this early; fallback to baseline |
| Graph construction overhead too high for real-time use | Low | Medium | Cache graph representations; AST graphs are small for typical functions |
| Rust AST parsing differences from Tree-sitter assumptions | Medium | Low | SafeNet already has Rust AST extraction; adapt Code2Graph to existing format |
| GNN overfits on small knowledge base (89 patterns) | Medium | Medium | Use dropout, weight decay, data augmentation; GNN's inductive bias may actually help with small data |
| Complexity creep — full GNN-Coder is more than needed | High | Medium | Start minimal (Phase 1), only add complexity if justified by gains |
| Consumer hardware constraint violated | Low | High | Keep GNN lightweight; monitor parameter count and inference time |

---

## 9. Conclusion

**GNN-Coder is a strong candidate for improving SafeNet's AST representation.** The core insight — that flattening AST loses structural information that matters for code understanding — directly applies to SafeNet's weakness. The child-node-aware pooling is a principled innovation that should help with pattern disambiguation.

**Key question for prototype:** Does the GNN actually help distinguish between SafeNet's fine-grained unsafe code patterns? The CSN results show 1-10% improvement for code retrieval, but SafeNet's task is different (pattern matching within a constrained domain). The Phase 1 feasibility study is designed to answer this.

**If GNN-Coder alone doesn't deliver:** The graph construction infrastructure can still be valuable as a foundation for other structural enhancements (dataflow edges, type annotations, etc.) even if the GNN component is simplified or replaced.

---

## 10. References

1. Ye, Y., Pang, P., Zhang, T., & Huang, H. (2025). GNN-Coder: Boosting Semantic Code Retrieval with Combined GNNs and Transformer. arXiv:2502.15202.

2. Dong, Y., Zhang, Z., Cui, M., & Xu, H. (2024). SafeNet: Towards mitigating replaceable unsafe Rust code via a recommendation-based approach. Software Testing, Verification & Reliability, 34(5), e1875.

3. Allamanis, M., Brockschmidt, M., & Khademi, M. (2017). Learning to represent programs with graphs. arXiv:1711.00740.

4. Alon, U., Zilberstein, M., Levy, O., & Yahav, E. (2019). Code2vec: Learning distributed representations of code. POPL 2019.

5. Feng, Z., et al. (2020). CodeBERT: A pre-trained model for programming and natural languages. Findings of EMNLP 2020.

---

*End of evaluation.*