# Research vectors

> **Status: active · Updated: 2026-10-24**

Directions for improving on the SafeNet baseline (Dong et al.).

## Replace BERT

Should be more modern than BERT (2024–2027). Must be similarly lightweight on
training and inference.

## Integrate GNN for AST Structure Learning

- SafeNet flattens the AST to a preorder traversal sequence. We should overcome
  flattening to improve accuracy.
- Ye et al., 2025 — GNN-Coder is a good candidate. Evaluate this candidate.

See the [GNN-Coder evaluation](gnn-coder-evaluation.md) and the
[prototype README](../../research/gnn/README.md).

**Proposed architecture enhancement:**

```text
Dong et al.: AST → Preorder Traversal → BERT → SNN
Proposed:    AST → Graph Construction → GNN + Transformer Fusion → Enhanced Embeddings
```

## Expand knowledge-base coverage and pattern granularity

- Only **19 unsafe APIs** are covered (out of many more in the standard library).
- Use unsafe-to-safe examples from modern documentation, including unofficial
  high-quality sources such as advisories.
- Add data for irreplaceable, conditionally replaceable, and encapsulatable code
  to reduce false positives. Synthetic dataset generation may help.
- The data, label, and split design is in the
  [transition dataset plan](transition-dataset.md).

## Enhance dataflow analysis with advanced static analysis

### Current limitation

- Simple union-find-based alias analysis (Algorithm 2 in the paper).
- Limited to intra-procedural analysis.
- “The power of such analysis is limited because a code snippet may demonstrate
  the characteristics of multiple patterns.”

### Improvement opportunities

1. **Inter-procedural analysis**
   - Track data flow across function boundaries.
   - Build call graphs for context.

2. **Type-based constraints**
   - Leverage Rust's strong type system more fully.
   - Use type inference to disambiguate patterns.
   - Example: `Box::from_raw` patterns can be distinguished by the raw pointer
     type and how it is used.

3. **Points-to analysis refinement**
   - Current: basic alias analysis.
   - Better: Steensgaard-style or Anderson-style pointer analysis.
   - The codebase already has `steengaard.rs`; it could be enhanced.

4. **Pattern-specific constraint solvers**
   - For each pattern, define formal constraints.
   - Use SMT solvers or custom constraint propagation.
   - Example: pattern 1 of `Box::from_raw` requires backward dataflow to the raw
     pointer parameter.

Unsafe APIs introduce pre- and post-conditions. These should be followed
throughout the project and, where possible, enforced by encapsulation.

## Multi-modal embedding architecture

### Current limitation

- Relies solely on AST-based token sequences.
- Does not use:
  - control-flow information;
  - data-flow graphs;
  - type information;
  - semantic annotations.

## Leverage LLM-based code understanding

Agentic LLMs may be strong enough to propose a patch (see `git diff`) that
replaces or encapsulates some unsafe usage.

## Improved training strategy and loss functions

### Current limitation

- BERT is frozen during SNN training.
- Simple cosine embedding loss.
- Binary similarity labels (`1/-1`).
- A 32-dimensional bottleneck may lose information.

### Improvement opportunities

1. **Unfreeze BERT layers with differential learning rates**
   - Lower layers: smaller LR to preserve general code knowledge.
   - Higher layers: larger LR to adapt to unsafe code patterns.

2. **Advanced loss functions**
   - **Triplet loss** with hard-negative mining.
   - **Contrastive loss** with temperature scaling.
   - **InfoNCE loss** for better representation learning.

3. **Multi-task learning**
   - Primary task: pattern matching.
   - Auxiliary tasks:
     - API type classification;
     - replaceability prediction;
     - safety-guarantee classification.

4. **Better embedding dimensionality**
   - Current: 32 dimensions (possibly too compressed).
   - Experiment with 64, 128, and 256 dimensions.
   - Use learned dimensionality reduction (autoencoder-style).

5. **Data augmentation for code**
   - Variable renaming.
   - Equivalent code transformations.
   - Add synthetic variants of knowledge-base samples.

## Maintain accessible inference and training

Do not employ large LLMs or other expensive technology outside the suggestion
process.

## Evaluation improvements

### Current

Only pattern-recognition accuracy.

### Enhanced metrics

- **Recommendation usefulness:** does the developer accept the recommendation?
- **Safety improvement:** does the replacement actually improve safety?
- **Performance impact:** does the replacement maintain performance?
- **False-positive rate:** how often does it incorrectly flag necessary unsafe
  code?
