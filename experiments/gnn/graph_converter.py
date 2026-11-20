"""
Graph Converter for SafeNet GNN Integration
Converts SafeNet's simplified AST format to PyTorch Geometric graph format.
Based on GNN-Coder's Code2Graph approach (Ye et al., 2025).
"""

import json
import torch
from typing import Dict, List
from collections import defaultdict


class ASTNode:
    """Represents a node in the AST graph."""
    def __init__(self, node_id: int, node_type: str, value: str = ""):
        self.id = node_id
        self.type = node_type
        self.value = value
        self.children: List[int] = []
        self.num_children = 0
        
    def add_child(self, child_id: int):
        self.children.append(child_id)
        self.num_children += 1


class ASTGraphBuilder:
    """Builds a graph representation from SafeNet's simplified AST format."""
    
    NODE_TYPE_VOCAB = {
        'Block': 0, 'Expr': 1, 'Stmt': 2, 'ident': 3, 'token': 4,
        'Call': 5, 'MethodCall': 6, 'Path': 7, 'Reference': 8,
        'Mut': 9, 'Const': 10, 'Deref': 11, 'Index': 12, 'Field': 13,
        'Struct': 14, 'Enum': 15, 'Match': 16, 'If': 17, 'Loop': 18,
        'While': 19, 'For': 20, 'Return': 21, 'Let': 22, 'Assign': 23,
        'Binary': 24, 'Unary': 25, 'Cast': 26, 'Type': 27, 'TypeRef': 28,
        'Ptr': 29, 'Array': 30, 'Tuple': 31, 'Record': 32, 'Lifetime': 33,
        'Generic': 34, 'Param': 35, 'Arg': 36, 'Fn': 37, 'Impl': 38,
        'Trait': 39, 'Use': 40, 'Mod': 41, 'Static': 42, 'unsafe': 43,
        'Eq': 44, 'Colon2': 45, 'Dot2': 46, 'And': 47, 'Star': 48,
        'Lt': 49, 'Gt': 50, 'Bracket': 51, 'HalfOpen': 52,
        'MutToken': 53, 'StarToken': 54, 'AndToken': 55,
        'LtToken': 56, 'GtToken': 57, 'Default': 58,
    }
    
    def __init__(self, max_nodes: int = 512):
        self.max_nodes = max_nodes
        self.nodes: Dict[int, ASTNode] = {}
        self.node_types: List[str] = []
        self.node_values: List[str] = []
        self.edges_src: List[int] = []
        self.edges_dst: List[int] = []
    def __init__(self, max_nodes: int = 512):
        self.max_nodes = max_nodes
        self.nodes: Dict[int, ASTNode] = {}
        self.node_types: List[str] = []
        self.node_values: List[str] = []
        self.edges_src: List[int] = []
        self.edges_dst: List[int] = []
        self.node_counter = 0
    
    def parse_simplified_ast(self, ast_string: str) -> 'ASTGraphBuilder':
        """Parse SafeNet's simplified AST string into a graph."""
        self.__init__()
        tokens = self._tokenize(ast_string)
        self._build_tree(tokens)
        return self
    
    def _tokenize(self, ast_string: str) -> List[str]:
        """Tokenize the simplified AST string into meaningful tokens."""
        tokens = []
        current = ""
        for char in ast_string:
            if char in '()':
                if current:
                    tokens.append(current)
                    current = ""
                tokens.append(char)
            else:
                current += char
        if current:
            tokens.append(current)
        return tokens
    
    def _build_tree(self, tokens: List[str]):
        """Build tree structure from tokenized AST."""
        stack = [(0, None)]
        current_id = 0
        
        i = 0
        while i < len(tokens):
            token = tokens[i]
            
            if token == '(':
                if i + 1 < len(tokens):
                    i += 1
                    node_type = tokens[i]
                    
                    self.nodes[current_id] = ASTNode(current_id, node_type)
                    self.node_types.append(node_type)
                    self.node_values.append("")
                    
                    if stack and stack[-1][0] != current_id:
                        parent_id = stack[-1][0]
                        self.edges_src.append(parent_id)
                        self.edges_dst.append(current_id)
                        self.nodes[parent_id].add_child(current_id)
                    
                    stack.append((current_id, stack[-1][0] if stack else None))
                    current_id += 1
                    
            elif token == ')':
                if len(stack) > 1:
                    stack.pop()
            else:
                if stack:
                    current_node_id = stack[-1][0]
                    if current_node_id in self.nodes:
                        self.nodes[current_node_id].value = token
                        self.node_values[-1] = token if self.node_values else token
            
            i += 1
    
    def get_node_type_id(self, node_type: str) -> int:
        return self.NODE_TYPE_VOCAB.get(node_type, self.NODE_TYPE_VOCAB['Default'])
    
    def to_pyg_format(self) -> Dict:
        """Convert the built graph to PyTorch Geometric compatible format."""
        num_nodes = len(self.nodes)
        if num_nodes == 0:
            return None
            
        num_node_types = len(self.NODE_TYPE_VOCAB)
        x = torch.zeros(num_nodes, num_node_types)
        
        for node_id, node in self.nodes.items():
            type_id = self.get_node_type_id(node.type)
            if type_id < num_node_types:
                x[node_id, type_id] = 1.0
        
        if self.edges_src:
            edge_index = torch.tensor(
                [self.edges_src, self.edges_dst], dtype=torch.long
            )
        else:
            edge_index = torch.tensor(
                [list(range(num_nodes)), list(range(num_nodes))],
                dtype=torch.long
            )
        
        node_values = []
        for node_id in range(num_nodes):
            if node_id in self.nodes:
                node_values.append(self.nodes[node_id].value)
            else:
                node_values.append("")
        
        node_importance = torch.zeros(num_nodes)
        for node_id, node in self.nodes.items():
            node_importance[node_id] = node.num_children
        
        return {
            'x': x,
            'edge_index': edge_index,
            'node_values': node_values,
            'node_importance': node_importance,
            'num_nodes': num_nodes,
        }
    
    def get_graph_stats(self) -> Dict:
        return {
            'num_nodes': len(self.nodes),
            'num_edges': len(self.edges_src),
            'avg_children': sum(n.num_children for n in self.nodes.values()) / max(len(self.nodes), 1),
            'max_children': max((n.num_children for n in self.nodes.values()), default=0),
        }
        self.node_counter = 0

class Code2Graph:
    """
    Main interface for converting code AST to graph format.
    Based on GNN-Coder's Code2Graph approach (Ye et al., 2025).
    """
    
    def __init__(self, max_nodes: int = 512):
        self.builder = ASTGraphBuilder(max_nodes)
        
    def convert(self, ast_string: str) -> Dict:
        """Convert a simplified AST string to graph format."""
        self.builder.parse_simplified_ast(ast_string)
        return self.builder.to_pyg_format()
    
    def convert_file(self, input_path: str, output_path: str):
        """Convert an AST file to graph format and save as JSON."""
        with open(input_path, 'r') as f:
            ast_string = f.read().strip()
        
        graph_data = self.convert(ast_string)
        
        serializable = {
            'x': graph_data['x'].tolist() if graph_data else [],
            'edge_index': graph_data['edge_index'].tolist() if graph_data else [],
            'node_values': graph_data.get('node_values', []),
            'node_importance': graph_data.get('node_importance', torch.tensor([])).tolist(),
            'num_nodes': graph_data['num_nodes'] if graph_data else 0,
        }
        
        with open(output_path, 'w') as f:
            json.dump(serializable, f)
        
        return graph_data
    
    def batch_convert(self, input_dir: str, output_dir: str, pattern: str = '.ast'):
        """Convert all AST files in a directory to graph format."""
        import os
        os.makedirs(output_dir, exist_ok=True)
        
        for filename in os.listdir(input_dir):
            if filename.endswith(pattern):
                input_path = os.path.join(input_dir, filename)
                output_filename = filename.replace(pattern, '.graph.json')
                output_path = os.path.join(output_dir, output_filename)
                
                try:
                    self.convert_file(input_path, output_path)
                    print(f"Converted: {filename} -> {output_filename}")
                except Exception as e:
                    print(f"Error converting {filename}: {e}")


def load_graph_from_json(path: str) -> Dict:
    """Load graph data from JSON file and convert back to tensors."""
    with open(path, 'r') as f:
        data = json.load(f)
    
    return {
        'x': torch.tensor(data['x'], dtype=torch.float),
        'edge_index': torch.tensor(data['edge_index'], dtype=torch.long),
        'node_values': data.get('node_values', []),
        'node_importance': torch.tensor(data.get('node_importance', [])),
        'num_nodes': data['num_nodes'],
    }


if __name__ == "__main__":
    import sys
    
    if len(sys.argv) > 1:
        input_file = sys.argv[1]
        output_file = sys.argv[2] if len(sys.argv) > 2 else None
        
        converter = Code2Graph()
        
        if output_file:
            converter.convert_file(input_file, output_file)
            print(f"Saved graph to {output_file}")
        else:
            with open(input_file, 'r') as f:
                ast = f.read()
            graph = converter.convert(ast)
            print(f"Graph stats: {converter.builder.get_graph_stats()}")
    else:
        demo_ast = "(Block (Expr (Call (Path ident:main))))"
        converter = Code2Graph()
        graph = converter.convert(demo_ast)
        print("Demo graph:")
        print(f"  Nodes: {graph['num_nodes']}")
        print(f"  Edges: {graph['edge_index'].shape[1]}")
        print(f"  Node features shape: {graph['x'].shape}")
