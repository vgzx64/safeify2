"""Minimal synchronous rust-analyzer LSP client (pure Python, stdlib only).

Notes for this rust-analyzer build (2026-08-24 tag):
  - The bare `rust-analyzer` binary speaks LSP on stdio; there is NO --stdio flag.
  - Loose .rs files (SafeNet testdata / synth snippets) are wrapped in a temp
    Cargo project with src/lib.rs symlinked to the original, so positions in
    responses map back to the real file.

Only the surface needed by the detector is implemented: initialize/initialized,
didOpen, hover, definition; server->client requests are auto-answered.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import tempfile
import time
from dataclasses import dataclass, field
from pathlib import Path


def utf16_col(line_text: str, char_col: int) -> int:
    """Convert a 0-based char column to a 0-based UTF-16 code-unit column."""
    col = 0
    for ch in line_text:
        if col >= char_col:
            break
        col += 2 if ord(ch) > 0xFFFF else 1
    return col


def offset_to_position(src: str, offset: int, use_utf16: bool = True) -> dict:
    line = src.count("\n", 0, offset)
    line_start = src.rfind("\n", 0, offset) + 1
    char_col = offset - line_start
    if use_utf16:
        nl = src.find("\n", line_start)
        line_text = src[line_start : nl if nl != -1 else len(src)]
        col = utf16_col(line_text, char_col)
    else:
        col = char_col
    return {"line": line, "character": col}


def find_project_root(path: Path) -> Path | None:
    d = path.resolve().parent
    while True:
        if (d / "Cargo.toml").exists():
            return d
        if d.parent == d:
            return None
        d = d.parent


def make_detached_project(path: Path) -> Path:
    """Temp cargo project with src/lib.rs symlinked to `path`."""
    tmp = Path(tempfile.mkdtemp(prefix="ra_detect_"))
    (tmp / "Cargo.toml").write_text(
        '[package]\nname = "detect_target"\nversion = "0.0.0"\nedition = "2021"\n'
    )
    (tmp / "src").mkdir()
    (tmp / "src" / "lib.rs").symlink_to(path.resolve())
    return tmp


def _is_pkg_source(path: Path, root: Path) -> bool:
    """Whether `path` is inside the package's src/ (a real crate target)."""
    try:
        return path.resolve().is_relative_to(root.resolve() / "src")
    except (OSError, ValueError):
        return False


def ra_env() -> dict:
    """Env for the rust-analyzer child: prefer the rust-src shim `rustc` if
    present (see setup_rust_src_shim), so RA can load the standard library
    even when the real toolchain lacks the rust-src component."""
    env = os.environ.copy()
    shim = Path.home() / ".local" / "share" / "ra-detect" / "shim"
    if (shim / "rustc").exists():
        env["PATH"] = f"{shim}:{env.get('PATH', '')}"
    return env


def _flatten_markup(contents) -> str:
    """LSP MarkupContent | MarkedString | [..] -> plain text string."""
    parts: list[str] = []

    def take(c) -> None:
        if isinstance(c, str):
            parts.append(c)
        elif isinstance(c, dict):
            if "value" in c:
                parts.append(str(c["value"]))
        elif isinstance(c, list):
            for x in c:
                take(x)

    take(contents)
    return "\n".join(parts)


def _strip_fences(text: str) -> str:
    """Drop ```rust fences from hover markdown; keep bare lines."""
    lines = [ln for ln in text.splitlines()
             if not ln.strip().startswith("```")]
    return "\n".join(lines).strip()


@dataclass
class Analyzer:
    ra_bin: str = "rust-analyzer"
    ready_timeout: float = 45.0
    request_timeout: float = 15.0
    _proc: subprocess.Popen | None = field(default=None, repr=False)
    _next_id: int = field(default=1, repr=False)
    _last_roundtrip: bool = field(default=False, repr=False)
    _diagnostics_seen: bool = field(default=False, repr=False)
    _buf: bytes = field(default=b"", repr=False)
    _tmpdir: Path | None = field(default=None, repr=False)
    doc_uri: str = ""
    doc_src: str = ""

    # ------------------------------------------------------------ lifecycle --

    def open_file(self, path: str | Path) -> None:
        """Start rust-analyzer and didOpen the given file."""
        path = Path(path).resolve()
        src = path.read_text(errors="replace")
        self.doc_src = src
        root = find_project_root(path)
        # A stray file inside a foreign crate (e.g. vendors/SafeNet/testdata/*)
        # would make rust-analyzer re-index the whole crate per file — slow,
        # and hover would return null anyway since the file is not a crate
        # target. Only honor the project root when the file lives under src/.
        if root is not None and not _is_pkg_source(path, root):
            root = None
        if root is None:
            root = make_detached_project(path)
            self._tmpdir = root
            # rust-analyzer only analyzes documents inside the workspace; open
            # the in-workspace symlink (same inode -> spans map back 1:1).
            doc_path = root / "src" / "lib.rs"
        else:
            doc_path = path
        self._proc = subprocess.Popen(
            [self.ra_bin],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            cwd=str(root),
            env=ra_env(),
        )
        self.request(
            "initialize",
            {
                "processId": os.getpid(),
                "rootUri": root.as_uri(),
                "capabilities": {
                    "textDocument": {
                        "hover": {"contentFormat": ["markdown", "plaintext"]},
                        "definition": {},
                    },
                    "general": {"positionEncodings": ["utf-16"]},
                },
            },
        )
        self._send({"jsonrpc": "2.0", "method": "initialized", "params": {}})
        self.doc_uri = doc_path.as_uri()
        self._send({
            "jsonrpc": "2.0",
            "method": "textDocument/didOpen",
            "params": {"textDocument": {
                "uri": self.doc_uri, "languageId": "rust",
                "version": 1, "text": src,
            }},
        })
        self._wait_ready()

    def close(self) -> None:
        if self._proc is None:
            return
        try:
            self.request("shutdown", None, timeout=5.0)
            self._send({"jsonrpc": "2.0", "method": "exit"})
            self._proc.wait(timeout=5)
        except Exception:
            self._proc.kill()
        finally:
            self._proc = None
            if self._tmpdir is not None:
                shutil.rmtree(self._tmpdir, ignore_errors=True)
                self._tmpdir = None

    def __enter__(self) -> "Analyzer":
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    # ------------------------------------------------------------- requests --

    def hover(self, offset: int) -> str | None:
        pos = offset_to_position(self.doc_src, offset)
        for attempt in range(3):
            res = self.request("textDocument/hover", {
                "textDocument": {"uri": self.doc_uri}, "position": pos,
            })
            if res and res.get("contents"):
                return _strip_fences(_flatten_markup(res["contents"]))
            time.sleep(0.3)  # crate loading may still be in flight
        return None

    def definition(self, offset: int) -> dict | None:
        pos = offset_to_position(self.doc_src, offset)
        res = self.request("textDocument/definition", {
            "textDocument": {"uri": self.doc_uri}, "position": pos,
        })
        if not res:
            return None
        if isinstance(res, list):
            res = res[0] if res else None
        return res

    def request(self, method: str, params, timeout: float | None = None):
        timeout = timeout or self.request_timeout
        rid = self._next_id
        self._next_id += 1
        self._send({"jsonrpc": "2.0", "id": rid, "method": method, "params": params})
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            msg = self._read_message(deadline - time.monotonic())
            if msg is None:
                break
            if msg.get("id") == rid and ("result" in msg or "error" in msg):
                if "error" in msg:
                    self._last_roundtrip = True
                    return None
                self._last_roundtrip = True
                return msg.get("result")
        return None

    def _wait_ready(self) -> bool:
        """Wait until rust-analyzer publishes diagnostics for the opened doc
        (i.e. the crate is loaded and semantic info exists)."""
        deadline = time.monotonic() + self.ready_timeout
        while time.monotonic() < deadline and not self._diagnostics_seen:
            self._read_message(min(1.0, max(deadline - time.monotonic(), 0.05)))
        self._last_roundtrip = self._diagnostics_seen
        return self._diagnostics_seen

    # ----------------------------------------------------------------- IO ----

    def _send(self, msg: dict) -> None:
        body = json.dumps(msg).encode()
        self._proc.stdin.write(
            b"Content-Length: %d\r\n\r\n" % len(body) + body)
        self._proc.stdin.flush()

    def _read_message(self, timeout: float) -> dict | None:
        """Read one LSP message, auto-answering server->client requests."""
        import select

        deadline = time.monotonic() + max(timeout, 0.05)
        while True:
            hdr_end = self._buf.find(b"\r\n\r\n")
            if hdr_end != -1:
                headers = self._buf[:hdr_end].decode(errors="replace")
                m = re.search(r"Content-Length:\s*(\d+)", headers, re.I)
                if m:
                    n = int(m.group(1))
                    body_start = hdr_end + 4
                    if len(self._buf) >= body_start + n:
                        body = self._buf[body_start : body_start + n]
                        self._buf = self._buf[body_start + n :]
                        return self._dispatch(json.loads(body))
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return None
            r, _, _ = select.select([self._proc.stdout], [], [], remaining)
            if not r:
                return None
            # read1: return after the first underlying read (read() would block
            # until 65536 bytes accumulate on a quiet pipe)
            read1 = getattr(self._proc.stdout, "read1", self._proc.stdout.read)
            chunk = read1(65536)
            if not chunk:
                return None
            self._buf += chunk

    def _dispatch(self, msg: dict) -> dict | None:
        if "id" in msg and "method" in msg:  # server -> client request
            self._answer_server_request(msg)
            return None
        if msg.get("method") == "textDocument/publishDiagnostics":
            if msg.get("params", {}).get("uri") == self.doc_uri:
                self._diagnostics_seen = True
            return None
        if "id" in msg and ("result" in msg or "error" in msg):
            return msg
        return None  # other notifications: ignored for now

    def _answer_server_request(self, msg: dict) -> None:
        method = msg.get("method", "")
        if method in ("workspace/configuration",):
            result: object = [{} for _ in (msg.get("params", {})
                                           .get("items", [1]))]
        elif method in ("client/registerCapability", "client/unregisterCapability",
                        "window/workDoneProgress/create"):
            result = None
        else:
            result = None  # unknown: answer null to unblock the server
        reply = {"jsonrpc": "2.0", "id": msg["id"], "result": result}
        try:
            self._send(reply)
        except Exception:
            pass


if __name__ == "__main__":
    import sys

    with Analyzer() as a:
        a.open_file(sys.argv[1])
        print("ready:", a._last_roundtrip, "doc:", a.doc_uri)
        print("hover(0):", (a.hover(0) or "")[:80])


