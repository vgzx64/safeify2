#!/usr/bin/env python3
"""Test script for GNN-Coder integration."""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

def test_graph_converter():
    """Test AST to graph conversion."""
    print("=" * 60)
    print("Testing Graph Converter")
    print("=" * 60)
    
    from gnn.graph_converter import Code2Graph
    
    demo_asts = [
        "(Block (Expr (Call (Path ident:main))))",
        "(Block (Stmt (Let (Path ident:x) (Call (Path ident:len)))))",
    ]
    
    for i, ast in enumerate(demo_asts):
        print(f"\nTest {i+1}: {ast[:50]}...")
        converter = Code2Graph()
        graph = converter.convert(ast)
        print(f"  Nodes: {graph['num_nodes']}, Edges: {graph['edge_index'].shape[1]}")
        print(f"  Feature dim: {graph['x'].shape[1]}")
    
    print("\n✓ Graph converter tests passed")


def test_gnn_encoder():
    """Test GNN encoder."""
    print("\n" + "=" * 60)
    print("Testing GNN Encoder")
    print("=" * 60)
    
    import torch
    from gnn.ast_gnn import ASTGNN
    from gnn.graph_converter import Code2Graph
    
    converter = Code2Graph()
    graph = converter.convert("(Block (Expr (Call (Path ident:main))))")
    
    gnn = ASTGNN(in_channels=59, hidden_channels=64, out_channels=32, num_layers=2)
    emb = gnn(graph)
    print(f"  Output shape: {emb.shape}, Norm: {emb.norm().item():.4f}")
    
    graph2 = converter.convert("(Block (Expr (Call (Path ident:test))))")
    sim = gnn.similarity(graph, graph2)
    print(f"  Similarity: {sim.item():.4f}")
    
    print("\n✓ GNN encoder tests passed")


def test_combined_model():
    """Test combined GNN + BERT model."""
    print("\n" + "=" * 60)
    print("Testing Combined GNN + BERT Model")
    print("=" * 60)
    
    try:
        from transformers import BertModel, BertConfig
        from gnn.gnn_encoder import CombinedGNNBERT
        from gnn.graph_converter import Code2Graph
        
        config = BertConfig(vocab_size=1000, hidden_size=128, num_hidden_layers=2,
                           num_attention_heads=4, intermediate_size=256)
        bert = BertModel(config)
        
        model = CombinedGNNBERT(bert_model=bert, use_gnn=True, gnn_in=59, gnn_hid=64,
                               gnn_out=32, gnn_layers=2, fusion_dim=64, final_dim=32)
        
        converter = Code2Graph()
        graph1 = converter.convert("(Block (Expr (Call (Path ident:main))))")
        graph2 = converter.convert("(Block (Expr (Call (Path ident:test))))")
        
        batch_size, seq_len = 2, 20
        ids1 = torch.randint(0, 1000, (batch_size, seq_len))
        mask1 = torch.ones(batch_size, seq_len)
        ids2 = torch.randint(0, 1000, (batch_size, seq_len))
        mask2 = torch.ones(batch_size, seq_len)
        
        emb1, emb2 = model(ids1, mask1, ids2, mask2, graph1, graph2)
        print(f"  Emb1 shape: {emb1.shape}, Emb2 shape: {emb2.shape}")
        sim = torch.cosine_similarity(emb1, emb2)
        print(f"  Cosine sim (batch): {sim}")
        
        print("\n✓ Combined model tests passed")
        
    except ImportError as e:
        print(f"\n⚠ Skipped (import error): {e}")


def test_bert_only():
    """Test BERT-only mode."""
    print("\n" + "=" * 60)
    print("Testing BERT-Only Mode (Ablation)")
    print("=" * 60)
    
    try:
        from transformers import BertModel, BertConfig
        from gnn.gnn_encoder import CombinedGNNBERT
        from gnn.graph_converter import Code2Graph
        
        config = BertConfig(vocab_size=1000, hidden_size=128, num_hidden_layers=2,
                           num_attention_heads=4, intermediate_size=256)
        bert = BertModel(config)
        
        model = CombinedGNNBERT(bert_model=bert, use_gnn=False, fusion_dim=64, final_dim=32)
        
        converter = Code2Graph()
        graph1 = converter.convert("(Block (Expr (Call (Path ident:main))))")
        
        batch_size, seq_len = 2, 20
        ids1 = torch.randint(0, 1000, (batch_size, seq_len))
        mask1 = torch.ones(batch_size, seq_len)
        ids2 = torch.randint(0, 1000, (batch_size, seq_len))
        mask2 = torch.ones(batch_size, seq_len)
        
        emb1, emb2 = model(ids1, mask1, ids2, mask2, graph1, graph1)
        print(f"  Emb1 shape: {emb1.shape}, Emb2 shape: {emb2.shape}")
        
        print("\n✓ BERT-only mode tests passed")
        
    except ImportError as e:
        print(f"\n⚠ Skipped (import error): {e}")


if __name__ == "__main__":
    import torch
    print("\n" + "=" * 60)
    print("GNN-Coder Integration Test Suite")
    print("=" * 60 + "\n")
    
    test_graph_converter()
    test_gnn_encoder()
    test_combined_model()
    test_bert_only()
    
    print("\n" + "=" * 60)
    print("All tests completed!")
    print("=" * 60)
