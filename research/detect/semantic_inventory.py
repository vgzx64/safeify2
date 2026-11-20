"""The semantic inventory `detect.py` consumes, from `safeify-lint --inventory`.

The engine parses the file with rust-analyzer and emits the `unsafe` regions,
the calls inside them (with resolved items where available), the raw derefs and
each function's guard context. This module adapts that JSON into the shape the
detector already works with, so `detect.py` no longer masks source text.

Two conversions live here:

* **Byte -> character offsets.** rust-analyzer (and the LSP) count UTF-8 bytes;
  the rest of `detect.py` slices the source as a Python string, and
  `ra_client.offset_to_position` wants a character index. Every offset from the
  engine is converted once, on load.
* **Region ownership.** The engine reports each region's own call list (nested
  regions repeat their children's calls, as the text scanner did); the detector
  keeps its own innermost-region attribution.

`inventory.py` stays in the tree as the reference implementation that
`inventory_parity.py` diffs against; this adapter is what the pipeline runs.
"""

from __future__ import annotations

import json
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
ENGINE = REPO / ".tools" / "cargo-target" / "engine" / "release" / "safeify-lint"


@dataclass
class UnsafeRegion:
    kind: str  # "block" (unsafe { }) or "fn" (unsafe fn)
    name: str | None
    start: int
    end: int
    body_start: int
    body_end: int

    def covers(self, off: int) -> bool:
        return self.start <= off < self.end


@dataclass
class Call:
    callee: str
    is_method: bool
    span: tuple[int, int]
    args: list[str] = field(default_factory=list)
    arg_spans: list[tuple[int, int]] = field(default_factory=list)
    resolved: str | None = None


@dataclass
class Deref:
    offset: int
    snippet: str
    raw_ptr: bool | None


@dataclass
class FnContext:
    fn_span: tuple[int, int] | None
    fn_name: str | None
    guards: list[str] = field(default_factory=list)
    signature: str = ""
    is_unsafe: bool = False


def _byte_to_char(src: str) -> list[int]:
    """Byte offset -> character index (rust-analyzer counts bytes)."""
    table = [0] * (len(src.encode()) + 1)
    byte = 0
    for index, ch in enumerate(src):
        for _ in range(len(ch.encode())):
            table[byte] = index
            byte += 1
    table[byte] = len(src)
    return table


class Inventory:
    """One file's inventory, with character offsets."""

    def __init__(self, data: dict, source: str):
        self.source = source
        self._map = _byte_to_char(source)

        def ch(offset: int) -> int:
            return self._map[min(offset, len(self._map) - 1)]

        self.regions = [
            UnsafeRegion(
                kind=r["kind"],
                name=r["name"],
                start=ch(r["start"]),
                end=ch(r["end"]),
                body_start=ch(r["body_start"]),
                body_end=ch(r["body_end"]),
            )
            for r in data["regions"]
        ]
        self._calls: dict[int, list[Call]] = {}
        self._derefs: dict[int, list[Deref]] = {}
        for raw, region in zip(data["regions"], self.regions):
            self._calls[region.start] = [
                Call(
                    callee=c["callee"],
                    is_method=c["is_method"],
                    span=(ch(c["span"][0]), ch(c["span"][1])),
                    args=list(c["args"]),
                    arg_spans=[(ch(a), ch(b)) for a, b in c["arg_spans"]],
                    resolved=c["resolved"],
                )
                for c in raw["calls"]
            ]
            self._derefs[region.start] = [
                Deref(offset=ch(d["offset"]), snippet=d["snippet"], raw_ptr=d["raw_ptr"])
                for d in raw["derefs"]
            ]
        self.functions = [
            FnContext(
                fn_span=(ch(f["span"][0]), ch(f["span"][1])),
                fn_name=f["name"],
                guards=list(f["guards"]),
                signature=f["signature"],
                is_unsafe=f["is_unsafe"],
            )
            for f in data["functions"]
        ]

    def calls_in(self, region: UnsafeRegion) -> list[Call]:
        return self._calls.get(region.start, [])

    def derefs_in(self, region: UnsafeRegion) -> list[Deref]:
        """Derefs worth reporting as `ptr::deref` candidates.

        A deref whose operand type resolved to something that is not a raw
        pointer is excluded — the text scanner could not tell, this can.
        Unresolved types stay, because a frozen snippet is full of types
        nothing in the file defines and dropping them loses real sites.
        """
        return [d for d in self._derefs.get(region.start, []) if d.raw_ptr is not False]

    def fn_context(self, offset: int) -> FnContext:
        """Enclosing function context for a sink at `offset`.

        Innermost `unsafe fn` first (that is the function whose safety contract
        the caller inherits), then the innermost function.
        """
        covering = [f for f in self.functions if f.fn_span[0] <= offset < f.fn_span[1]]
        if not covering:
            return FnContext(None, None, [], "")
        unsafe = [f for f in covering if f.is_unsafe]
        pool = unsafe or covering
        return min(pool, key=lambda f: f.fn_span[1] - f.fn_span[0])


def for_file(path: Path, engine: Path = ENGINE, timeout: int = 600) -> Inventory:
    if not engine.exists():
        raise RuntimeError(
            f"missing semantic engine: {engine}\n"
            "build it with research/detect/engine/cargo.sh build --release"
        )
    proc = subprocess.run(
        [str(engine), "--inventory", str(path)],
        capture_output=True,
        text=True,
        timeout=timeout,
    )
    if proc.returncode != 0:
        raise RuntimeError(f"{path}: safeify-lint exited {proc.returncode}: {proc.stderr[-400:]}")
    return Inventory(json.loads(proc.stdout), path.read_text(errors="replace"))


def offset_to_line_col(src: str, offset: int) -> tuple[int, int]:
    """0-based (line, char-column); UTF-16 conversion happens in ra_client."""
    line = src.count("\n", 0, offset)
    line_start = src.rfind("\n", 0, offset) + 1
    return line, offset - line_start
