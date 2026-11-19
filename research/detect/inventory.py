"""Unsafe-region inventory over Rust source, pure Python (no compiler).

Produces, for one file:
  - UnsafeRegion: spans of `unsafe { .. }` blocks and `unsafe fn` bodies
    (offset-preserving, comments/strings masked out so brace matching is safe).
  - Call: a call expression inside a region (method or path callee).
  - Guards: cheap syntactic evidence in the enclosing fn (null check, assert,
    with_capacity, len/capacity usage, overflow math).

Offsets are byte offsets into the original source; lines/cols are computed on
demand for the LSP (UTF-16 positions via ra_client.offset_to_position).
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

_WORD = re.compile(r"[A-Za-z0-9_]")


# ---------------------------------------------------------------- masking ---

def mask_source(src: str) -> str:
    """Return a copy of `src` where comments/strings/char-literals are blanked
    with spaces (newlines preserved) so offsets stay identical."""
    out = list(src)
    i, n = 0, len(src)

    def blank(a: int, b: int) -> None:
        for k in range(a, min(b, n)):
            if out[k] != "\n":
                out[k] = " "

    while i < n:
        c = src[i]
        prev = src[i - 1] if i else " "
        if c == "/" and i + 1 < n and src[i + 1] == "/":
            j = src.find("\n", i)
            blank(i, n if j == -1 else j)
            i = j if j != -1 else n
            continue
        if c == "/" and i + 1 < n and src[i + 1] == "*":
            j = i + 2
            while j + 1 < n and not (src[j] == "*" and src[j + 1] == "/"):
                j += 1
            blank(i, min(n, j + 2))
            i = min(n, j + 2)
            continue
        if not _WORD.match(prev):  # raw/byte string prefixes at word start
            m = re.match(r'b?r(#+)"', src[i:])
            if m:
                close = '"' + m.group(1)
                j = src.find(close, i + m.end())
                j = n if j == -1 else j + len(close)
                blank(i, j)
                i = j
                continue
            m = re.match(r'b"', src[i:])
            if m:
                j = i + 2  # skip the b and the opening quote, not just the b
                while j < n:
                    if src[j] == "\\":
                        j += 2
                        continue
                    if src[j] == '"':
                        j += 1
                        break
                    j += 1
                blank(i, j)
                i = j
                continue
        if c == '"':
            j = i + 1
            while j < n:
                if src[j] == "\\":
                    j += 2
                    continue
                if src[j] == '"':
                    j += 1
                    break
                j += 1
            blank(i, j)
            i = j
            continue
        if c == "'":
            if src[i + 1 : i + 2] == "\\":
                j = src.find("'", i + 2)
                j = n if j == -1 else j + 1
                blank(i, j)
                i = j
                continue
            m = re.match(r"'[A-Za-z_]\w*", src[i:])
            if m and (i + m.end() >= n or src[i + m.end()] != "'"):
                i += m.end()  # lifetime: keep
                continue
            j = src.find("'", i + 1)
            j = n if j == -1 else j + 1
            blank(i, j)
            i = j
            continue
        i += 1
    return "".join(out)


def find_matching(mask: str, open_idx: int, open_c: str = "{",
                  close_c: str = "}") -> int | None:
    """Index of the matching close char for mask[open_idx] == open_c."""
    if open_idx >= len(mask) or mask[open_idx] != open_c:
        return None
    depth = 0
    for i in range(open_idx, len(mask)):
        if mask[i] == open_c:
            depth += 1
        elif mask[i] == close_c:
            depth -= 1
            if depth == 0:
                return i
    return None


# ---------------------------------------------------------------- regions ---

@dataclass
class UnsafeRegion:
    kind: str  # "block" (unsafe { }) or "fn" (unsafe fn)
    name: str | None  # fn name for kind == "fn"
    start: int  # offset of `unsafe`
    end: int  # one past closing `}` (or fn body end)
    body_start: int  # inside the braces
    body_end: int  # offset of closing `}`

    def covers(self, off: int) -> bool:
        return self.start <= off < self.end


def find_unsafe_regions(src: str, mask: str | None = None) -> list[UnsafeRegion]:
    mask = mask if mask is not None else mask_source(src)
    regions: list[UnsafeRegion] = []
    for m in re.finditer(r"\bunsafe\b", mask):
        j = m.end()
        while j < len(mask) and mask[j] in " \t\r\n":
            j += 1
        if j >= len(mask):
            continue
        if mask[j] == "{":
            close = find_matching(mask, j)
            if close is None:
                continue
            regions.append(UnsafeRegion("block", None, m.start(), close + 1, j + 1, close))
        else:
            jj = j
            if mask.startswith("extern", jj):  # `unsafe extern "C" fn`
                jj += len("extern")
                while jj < len(mask) and mask[jj] in " \t\r\n\"":
                    jj += 1
            if not mask.startswith("fn", jj):
                continue
            k = jj + 2
            while k < len(mask) and mask[k] in " \t\r\n":
                k += 1
            name_m = re.match(r"[A-Za-z_]\w*", mask[k:])
            name = name_m.group(0) if name_m else None
            depth_p = depth_b = 0  # find body '{' at depth 0; skip `;` decls
            body = None
            for i in range(k, len(mask)):
                c = mask[i]
                if c == "(":
                    depth_p += 1
                elif c == ")":
                    depth_p -= 1
                elif c == "[":
                    depth_b += 1
                elif c == "]":
                    depth_b -= 1
                elif c == ";" and depth_p == 0 and depth_b == 0:
                    break  # extern-style decl, no body
                elif c == "{" and depth_p == 0 and depth_b == 0:
                    body = i
                    break
            if body is None:
                continue
            close = find_matching(mask, body)
            if close is None:
                continue
            regions.append(UnsafeRegion("fn", name, m.start(), close + 1, body + 1, close))
    return regions


def enclosing_fn(regions: list[UnsafeRegion], off: int) -> UnsafeRegion | None:
    fns = [r for r in regions if r.kind == "fn" and r.covers(off)]
    if not fns:
        return None
    return min(fns, key=lambda r: r.end - r.start)


# ------------------------------------------------------------------ calls ---

@dataclass
class Call:
    callee: str  # method name for method calls, path text for path calls
    is_method: bool
    open_paren: int
    close_paren: int
    args: list[str] = field(default_factory=list)
    arg_spans: list[tuple[int, int]] = field(default_factory=list)

    @property
    def span(self) -> tuple[int, int]:
        pad = len(self.callee) + (1 if self.is_method else 0)
        return (self.open_paren - pad, self.close_paren + 1)


_PATH_CALL = re.compile(r"(?<![\w.:])([A-Za-z_]\w*(?:::[A-Za-z_]\w*)*)\s*\(")
_METHOD_CALL = re.compile(r"\.\s*([A-Za-z_]\w*)\s*\(")


def _split_args(text: str, base: int) -> tuple[list[str], list[tuple[int, int]]]:
    """Split a masked argument list, keeping one span per positional argument.

    String literals are blanked by ``mask_source``, so an argument can be
    entirely whitespace in ``text``. Spans are therefore kept for every
    position and delimited by the surrounding commas, not by visible tokens;
    callers recover the real text from the unmasked source. Dropping blank
    segments would silently renumber the arguments of every call with a
    literal first argument.
    """
    if not text:
        return [], []
    args, spans = [], []
    depth = 0
    start = 0

    def add(seg: str, seg_start: int, seg_end: int) -> None:
        lead = len(seg) - len(seg.lstrip())
        a = base + seg_start + lead
        if a >= base + seg_end:  # masked-out literal: keep the segment start
            a = base + seg_start
        args.append(seg.strip())
        spans.append((a, base + seg_end))

    for i, c in enumerate(text):
        if c in "([{":
            depth += 1
        elif c in ")]}":
            depth -= 1
        elif c == "," and depth == 0:
            add(text[start:i], start, i)
            start = i + 1
    add(text[start:], start, len(text))
    return args, spans


def find_calls(mask: str, start: int, end: int) -> list[Call]:
    """All calls (method + path) whose callee starts inside [start, end)."""
    calls: list[Call] = []
    seen_parens: set[int] = set()
    for m in _METHOD_CALL.finditer(mask, start, end):
        open_p = m.end() - 1
        close = find_matching(mask, open_p, "(", ")")
        if close is None:
            continue
        args, spans = _split_args(mask[open_p + 1 : close], open_p + 1)
        calls.append(Call(m.group(1), True, open_p, close, args, spans))
        seen_parens.add(open_p)
    for m in _PATH_CALL.finditer(mask, start, end):
        open_p = m.end() - 1
        if open_p in seen_parens:
            continue
        close = find_matching(mask, open_p, "(", ")")
        if close is None:
            continue
        args, spans = _split_args(mask[open_p + 1 : close], open_p + 1)
        calls.append(Call(m.group(1), False, open_p, close, args, spans))
    calls.sort(key=lambda c: c.open_paren)
    return calls


# ------------------------------------------------------------ raw derefs ----

_DEREF_OK_PREV = set("=([{,;>&|")  # positions where `*p` is a deref, not arith/type


def find_raw_derefs(mask: str, start: int, end: int) -> list[tuple[int, str]]:
    """Offsets + snippet of unary `*place` derefs inside [start, end).

    Conservative: skips multiplication (prev is an operand), type positions
    (`*const T` after `:`/`->`/`as`), and function-pointer types.
    """
    out: list[tuple[int, str]] = []
    i = start
    while i < end:
        if mask[i] != "*":
            i += 1
            continue
        p = i - 1
        while p >= 0 and mask[p] in " \t\r\n":
            p -= 1
        prev = mask[p] if p >= 0 else "{"
        prev_word = re.findall(r"[A-Za-z_]\w*", mask[max(0, p - 7) : p + 1])
        prev_word = prev_word[-1] if prev_word else ""
        q = i + 1
        while q < end and mask[q] in " \t\r\n":
            q += 1
        nxt = mask[q] if q < end else ""
        if not (nxt.isalpha() or nxt == "_" or nxt == "("):
            i += 1
            continue
        ok = prev in _DEREF_OK_PREV or prev_word == "return"
        if ok:
            j = q
            if nxt == "(":
                close = find_matching(mask, q, "(", ")")
                j = (close + 1) if close is not None else q + 1
            else:
                while j < end and (mask[j].isalnum() or mask[j] in "_."):
                    j += 1
            out.append((i, mask[i:j].strip()))
        i += 1
    return out


# ---------------------------------------------------------------- guards ----

@dataclass
class FnContext:
    fn_span: tuple[int, int] | None  # enclosing `unsafe fn` span if any
    fn_name: str | None
    guards: list[str] = field(default_factory=list)
    signature: str = ""


_GUARD_DETECTORS = [
    ("null_check", re.compile(r"\bis_null\b")),
    ("assert", re.compile(r"\bdebug_assert|(?<![\w.])(?<![:])assert")),
    ("with_capacity", re.compile(r"\bwith_capacity\b")),
    ("len_cap", re.compile(r"\.(len|capacity)\s*\(")),
    ("overflow_math", re.compile(
        r"\b(saturating_(add|sub)|checked_(add|sub|mul)|wrapping_(add|sub))\b")),
    ("matches_macro", re.compile(r"\bmatches!")),
]


def fn_context(src: str, mask: str, regions: list[UnsafeRegion],
               off: int) -> FnContext:
    fn = enclosing_fn(regions, off)
    if fn is not None:
        body = mask[fn.body_start : fn.body_end]
        guards = [name for name, rx in _GUARD_DETECTORS if rx.search(body)]
        sig_start = mask.rfind("fn", fn.start, fn.body_start)
        sig = src[(sig_start if sig_start != -1 else fn.start) : fn.body_start].strip()
        return FnContext((fn.start, fn.end), fn.name, guards, sig)
    # fallback: nearest plain `fn` whose body encloses `off`
    last = None
    for m in re.finditer(r"\bfn\b", mask[:off]):
        last = m
    if last is not None:
        k = last.end()
        while k < len(mask) and mask[k] in " \t\r\n":
            k += 1
        name_m = re.match(r"[A-Za-z_]\w*", mask[k:])
        body = None
        depth = 0
        for i in range(k, len(mask)):
            c = mask[i]
            if c == "(":
                depth += 1
            elif c == ")":
                depth -= 1
            elif c == "{" and depth == 0:
                body = i
                break
            elif c == ";" and depth == 0:
                break
        if body is not None:
            close = find_matching(mask, body)
            if close is not None and close >= off:
                region_text = mask[body + 1 : close]
                guards = [name for name, rx in _GUARD_DETECTORS
                          if rx.search(region_text)]
                sig = src[last.start() : body].strip()
                return FnContext((last.start(), close + 1),
                                 name_m.group(0) if name_m else None,
                                 guards, sig)
    return FnContext(None, None, [], "")


def offset_to_line_col(src: str, offset: int) -> tuple[int, int]:
    """0-based (line, char-column); UTF-16 conversion happens in ra_client."""
    line = src.count("\n", 0, offset)
    line_start = src.rfind("\n", 0, offset) + 1
    return line, offset - line_start


def main() -> None:
    import sys

    for path in sys.argv[1:]:
        src = open(path).read()
        mask = mask_source(src)
        regions = find_unsafe_regions(src, mask)
        print(f"{path}: {len(regions)} unsafe region(s)")
        for r in regions:
            calls = find_calls(mask, r.body_start, r.body_end)
            derefs = find_raw_derefs(mask, r.body_start, r.body_end)
            print(f"  {r.kind} {r.name or ''} [{r.start},{r.end}) calls={len(calls)} "
                  f"derefs={len(derefs)}")


if __name__ == "__main__":
    main()



