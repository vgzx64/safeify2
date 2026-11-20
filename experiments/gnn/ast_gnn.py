"""AST GNN Encoder - GNN-Coder based implementation."""

import torch
import torch.nn as nn
import torch.nn.functional as F
from typing import Dict, Optional, Tuple


class ChildNodeAwarePooling(nn.Module):
    """GNN-Coder's innovative graph pooling using child node count."""
    
    def __init__(self, in_channels: int, out_channels: int):
        super().__init__()
        self.proj = nn.Linear(in_channels, out_channels)
        self.child_proj = nn.Sequential(
            nn.Linear(1, 16),
            nn.ReLU(),
            nn.Linear(16, out_channels)
        )
    
    def forward(self, x: torch.Tensor, edge_index: torch.Tensor,
                node_importance: Optional[torch.Tensor] = None,
                batch: Optional[torch.Tensor] = None):
        h = self.proj(x)
        
        if node_importance is not None:
            child_feat = node_importance.unsqueeze(-1).float()
            child_emb = self.child_proj(child_feat)
            h = h + child_emb
        
        if edge_index.size(1) > 0:
            src, dst = edge_index
            agg = torch.zeros_like(h)
            for i in range(x.size(0)):
                neighbors = dst[src == i]
                if len(neighbors) > 0:
                    agg[i] = h[neighbors].mean(dim=0)
            h = h + agg
        
        if batch is not None:
            unique_batches = torch.unique(batch)
            pooled = []
            for b in unique_batches:
                mask = (batch == b)
                if mask.sum() > 0:
                    pooled.append(h[mask].mean(dim=0))
            return torch.stack(pooled) if pooled else torch.zeros(1, h.size(1)), [1.0]
        else:
            return h.mean(dim=0, keepdim=True), [1.0]


class ASTGNNEncoder(nn.Module):
    """Multi-layer GCN encoder for AST graphs."""
    
    def __init__(self, in_channels=59, hidden_channels=128, out_channels=64,
                 num_layers=2, dropout=0.3):
        super().__init__()
        self.input_proj = nn.Linear(in_channels, hidden_channels)
        self.gnn_layers = nn.ModuleList([
            nn.Linear(hidden_channels, hidden_channels) for _ in range(num_layers)
        ])
        self.batch_norms = nn.ModuleList([
            nn.BatchNorm1d(hidden_channels) for _ in range(num_layers)
        ])
        self.output_proj = nn.Linear(hidden_channels, out_channels)
        self.pooling = ChildNodeAwarePooling(out_channels, out_channels)
        self.dropout = dropout
        
        for m in self.modules():
            if isinstance(m, nn.Linear):
                nn.init.xavier_uniform_(m.weight)
                if m.bias is not None:
                    nn.init.zeros_(m.bias)
    
    def forward(self, x, edge_index, node_importance=None, batch=None):
        h = F.relu(self.input_proj(x))
        h = F.dropout(h, self.dropout, training=self.training)
        
        for gnn_layer, bn in zip(self.gnn_layers, self.batch_norms):
            if edge_index.size(1) > 0:
                src, dst = edge_index
                agg = torch.zeros_like(h)
                for v in range(x.size(0)):
                    neighbors = dst[src == v]
                    if len(neighbors) > 0:
                        agg[v] = h[neighbors].mean(dim=0)
                h = h + agg
            
            h = gnn_layer(h.unsqueeze(0)).squeeze(0) if h.dim() == 1 else gnn_layer(h)
            h = F.relu(h)
            h = F.dropout(h, self.dropout, training=self.training)
        
        h = F.relu(self.output_proj(h))
        return self.pooling(h, edge_index, node_importance, batch)[0]


class ASTGNN(nn.Module):
    """Complete AST GNN model for code similarity."""
    
    def __init__(self, in_channels=59, hidden_channels=128, out_channels=32, 
                 num_layers=2, dropout=0.3):
        super().__init__()
        self.encoder = ASTGNNEncoder(in_channels, hidden_channels, out_channels * 2, 
                                      num_layers, dropout)
        self.project = nn.Sequential(
            nn.Linear(out_channels * 2, out_channels * 2),
            nn.ReLU(),
            nn.Dropout(dropout),
            nn.Linear(out_channels * 2, out_channels)
        )
        nn.init.xavier_uniform_(self.project[0].weight)
        nn.init.xavier_uniform_(self.project[3].weight)
    
    def forward(self, graph_data):
        x = graph_data['x']
        edge_index = graph_data['edge_index']
        node_importance = graph_data.get('node_importance')
        batch = torch.zeros(x.size(0), dtype=torch.long, device=x.device) if x.dim() == 2 else None
        
        h = self.encoder(x, edge_index, node_importance, batch)
        emb = self.project(h)
        return (emb / (emb.norm(dim=-1, keepdim=True) + 1e-8)).squeeze(0) if emb.dim() > 1 else emb
    
    def similarity(self, graph1, graph2):
        return F.cosine_similarity(self.forward(graph1).unsqueeze(0), 
                                   self.forward(graph2).unsqueeze(0))


if __name__ == "__main__":
    from graph_converter import Code2Graph
    converter = Code2Graph()
    graph = converter.convert("(Block (Expr (Call (Path ident:main))))")
    print("Graph stats:", converter.builder.get_graph_stats())
    gnn = ASTGNN(in_channels=59, hidden_channels=64, out_channels=32, num_layers=2)
    emb = gnn(graph)
    print(f"Embedding shape: {emb.shape}, norm: {emb.norm().item():.4f}")
