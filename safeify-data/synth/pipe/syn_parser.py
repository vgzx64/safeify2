"""Thin wrapper around the extract_ast CLI tool (syn `{:#?}` Debug dump)."""

import os
import subprocess
import tempfile

SYNTH_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
EXTRACT_BIN = os.path.join(SYNTH_ROOT, "tools", "extract_ast", "target", "release", "extract_ast")


def tool_available():
    return os.path.isfile(EXTRACT_BIN)


def parse_to_debug(source_rs_text):
    """Parse Rust source text -> syn Debug dump string (same as SafeNet's .ast)."""
    if not tool_available():
        raise RuntimeError(
            f"extract_ast not built: {EXTRACT_BIN} missing (run cargo build --release in tools/extract_ast)"
        )
    with tempfile.TemporaryDirectory() as tmp:
        in_dir = os.path.join(tmp, "in")
        out_dir = os.path.join(tmp, "out")
        os.makedirs(in_dir, exist_ok=True)
        src = os.path.join(in_dir, "snippet.rs")
        with open(src, "w", encoding="utf-8") as f:
            f.write(source_rs_text)
        proc = subprocess.run(
            [EXTRACT_BIN, in_dir, out_dir],
            capture_output=True, text=True,
        )
        ast_path = os.path.join(out_dir, "snippet.ast")
        if proc.returncode != 0 or not os.path.isfile(ast_path):
            raise ValueError(f"syn parse failed: {proc.stderr.strip() or proc.stdout.strip()}")
        with open(ast_path, "r", encoding="utf-8") as f:
            return f.read()


def extract_tree(in_dir, out_dir):
    """Run the extractor over a directory. Returns (ok, failed)."""
    if not tool_available():
        raise RuntimeError(
            f"extract_ast not built: {EXTRACT_BIN} missing (run cargo build --release in tools/extract_ast)"
        )
    proc = subprocess.run([EXTRACT_BIN, in_dir, out_dir], capture_output=True, text=True)
    ok = failed = -1
    for part in (proc.stdout or "").split():
        if part.startswith("extracted="):
            ok = int(part.split("=", 1)[1])
        elif part.startswith("failed="):
            failed = int(part.split("=", 1)[1])
    if failed == -1:
        raise RuntimeError(f"extract_ast failed: {proc.stderr.strip() or proc.stdout.strip()}")
    return ok, failed
