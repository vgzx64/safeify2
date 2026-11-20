"""
GNN + Transformer Combined Encoder
Based on GNN-Coder integration approach (Ye et al., 2025).
"""

import torch
import torch.nn as nn
import torch.nn.functional as F
from typing import Dict, Optional
from .ast_gnn import ASTGNNEncoder


class GNNTransformerFusion(nn.Module):
    """Fuses GNN and Transformer embeddings."""
    
    def __init__(self, gnn_dim=64, trans_dim=768, fusion_dim=128, final_dim=32, method='concat'):
        super().__init__()
        self.method = method
        
        if method == 'concat':
            self.fusion = nn.Sequential(
                nn.Linear(gnn_dim + trans_dim, fusion_dim),
                nn.ReLU(), nn.Dropout(0.1),
                nn.Linear(fusion_dim, fusion_dim),
                nn.ReLU(), nn.Dropout(0.1),
                nn.Linear(fusion_dim, final_dim)
            )
        elif method in ('gate', 'add'):
            self.gnn_proj = nn.Linear(gnn_dim, fusion_dim)
            self.trans_proj = nn.Linear(trans_dim, fusion_dim)
            if method == 'gate':
                self.gate = nn.Sequential(nn.Linear(fusion_dim * 2, fusion_dim), nn.Sigmoid())
            self.final = nn.Sequential(
                nn.Linear(fusion_dim, fusion_dim),
                nn.ReLU(), nn.Dropout(0.1),
            )
            self.out_proj = nn.Linear(fusion_dim, final_dim)
        
        for m in self.modules():
            if isinstance(m, nn.Linear):
                nn.init.xavier_uniform_(m.weight)
                if m.bias is not None:
                    nn.init.zeros_(m.bias)
    
    def forward(self, gnn_emb, trans_emb):
        gnn_2d = gnn_emb.unsqueeze(0) if gnn_emb.dim() == 1 else gnn_emb
        trans_2d = trans_emb.unsqueeze(0) if trans_emb.dim() == 1 else trans_emb
        
        if self.method == 'concat':
            fused = torch.cat([gnn_2d, trans_2d], dim=-1)
            out = self.fusion(fused)
        elif self.method == 'gate':
            g = self.gnn_proj(gnn_2d)
            t = self.trans_proj(trans_2d)
            gate = self.gate(torch.cat([g, t], dim=-1))
            fused = self.final(gate * g + (1 - gate) * t)
            out = self.out_proj(fused)
        else:  # add
            g = self.gnn_proj(gnn_2d)
            t = self.trans_proj(trans_2d)
            fused = self.final(g + t)
            out = self.out_proj(fused)
        
        out = out / (out.norm(dim=-1, keepdim=True) + 1e-8)
        return out.squeeze(0) if out.size(0) == 1 and gnn_emb.dim() == 1 else out


class CombinedGNNBERT(nn.Module):
    """Combined GNN + BERT model for code similarity."""
    
    def __init__(self, bert_model, use_gnn=True, gnn_in=59, gnn_hid=128, 
                 gnn_out=64, gnn_layers=2, fusion_dim=128, final_dim=32, 
                 fusion_method='concat', gnn_dropout=0.3):
        super().__init__()
        self.use_gnn = use_gnn
        self.bert = bert_model
        self.final_dim = final_dim
        
        if use_gnn:
            self.gnn = ASTGNNEncoder(gnn_in, gnn_hid, gnn_out, gnn_layers, gnn_dropout)
            self.gnn_proj = nn.Linear(gnn_out, fusion_dim)
            nn.init.xavier_uniform_(self.gnn_proj.weight)
            self.fusion = GNNTransformerFusion(gnn_dim=fusion_dim, trans_dim=bert_model.config.hidden_size,
                                                fusion_dim=fusion_dim, final_dim=final_dim, method=fusion_method)
        else:
            self.gnn = None
            self.gnn_proj = None
            self.bert_proj = nn.Sequential(
                nn.Linear(bert_model.config.hidden_size, fusion_dim),
                nn.ReLU(), nn.Dropout(0.1),
                nn.Linear(fusion_dim, final_dim)
            )
            nn.init.xavier_uniform_(self.bert_proj[0].weight)
            nn.init.xavier_uniform_(self.bert_proj[3].weight)
    
    def forward(self, ids1, mask1, ids2, mask2, graph1=None, graph2=None):
        out1 = self.bert(ids1, attention_mask=mask1).pooler_output
        out2 = self.bert(ids2, attention_mask=mask2).pooler_output
        
        if self.use_gnn and self.gnn is not None and graph1 is not None and graph2 is not None:
            g1 = self.gnn(graph1['x'], graph1['edge_index'], graph1.get('node_importance'),
                          torch.zeros(graph1['num_nodes'], dtype=torch.long, device=graph1['x'].device))
            g2 = self.gnn(graph2['x'], graph2['edge_index'], graph2.get('node_importance'),
                          torch.zeros(graph2['num_nodes'], dtype=torch.long, device=graph2['x'].device))
            gp1 = self.gnn_proj(g1)  # (fusion_dim,)
            gp2 = self.gnn_proj(g2)  # (fusion_dim,)
            
            # Expand GNN embeddings to match batch size
            batch_size = out1.size(0)
            gp1 = gp1.squeeze().unsqueeze(0).expand(batch_size, -1)  # (batch_size, fusion_dim)
            gp2 = gp2.squeeze().unsqueeze(0).expand(batch_size, -1)
            
            emb1 = self.fusion(gp1, out1)
            emb2 = self.fusion(gp2, out2)
        else:
            emb1 = self.bert_proj(out1)
            emb2 = self.bert_proj(out2)
        
        return emb1 / (emb1.norm(dim=-1, keepdim=True) + 1e-8), emb2 / (emb2.norm(dim=-1, keepdim=True) + 1e-8)
