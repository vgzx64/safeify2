#!/usr/bin/env python3
"""
AST to Graph Converter for SafeNet GNN Integration

Converts SafeNet's simplified AST files to graph JSON format
for use with the GNN-Coder based encoder.

Usage:
    python ast_to_graph.py [input_dir] [output_dir]
    
If no arguments provided, uses default paths.
"""

import os
import sys
import json

# Add the model code path to import gnn modules
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from model.code.gnn.graph_converter import Code2Graph


def convert_directory(input_dir: str, output_dir: str):
    """
    Convert all .ast files in input_dir to .graph.json files in output_dir.
    
    Args:
        input_dir: Directory containing simplified AST files
        output_dir: Directory to save graph JSON files
    """
    # Create output directory if it doesn't exist
    os.makedirs(output_dir, exist_ok=True)
    
    # Initialize converter
    converter = Code2Graph()
    
    # Find all .ast files
    ast_files = [f for f in os.listdir(input_dir) if f.endswith('.ast')]
    
    if not ast_files:
        print(f"No .ast files found in {input_dir}")
        return
    
    print(f"Found {len(ast_files)} AST files to convert")
    
    converted = 0
    failed = 0
    
    for filename in ast_files:
        input_path = os.path.join(input_dir, filename)
        output_filename = filename.replace('.ast', '.graph.json')
        output_path = os.path.join(output_dir, output_filename)
        
        try:
            converter.convert_file(input_path, output_path)
            converted += 1
            print(f"✓ {filename} -> {output_filename}")
        except Exception as e:
            failed += 1
            print(f"✗ {filename}: {e}")
    
    print(f"\nConversion complete: {converted} succeeded, {failed} failed")


def main():
    """Main entry point."""
    import argparse
    
    parser = argparse.ArgumentParser(
        description='Convert SafeNet AST files to graph format for GNN processing'
    )
    parser.add_argument(
        'input_dir',
        nargs='?',
        default='/home/rose/code/similar/0623data/testsimpleast',
        help='Directory containing simplified AST files (.ast)'
    )
    parser.add_argument(
        'output_dir',
        nargs='?',
        default='/home/rose/code/similar/0623data/graph_output',
        help='Directory to save graph JSON files (.graph.json)'
    )
    
    args = parser.parse_args()
    
    print(f"Converting AST files from: {args.input_dir}")
    print(f"Output directory: {args.output_dir}\n")
    
    convert_directory(args.input_dir, args.output_dir)


if __name__ == "__main__":
    main()
