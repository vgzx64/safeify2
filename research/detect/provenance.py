"""Provenance and guard facts for the safe-Rust lints.

The attack patterns of Hassnain & Stanford, "Counterexamples in Safe Rust"
(ASEW '24), live in *safe* code, so `inventory.find_unsafe_regions` never sees
them and `verdict.py` cannot classify them: it only knows the 19 unsafe APIs.
What the lints need is a coarse lattice over an argument expression:

    literal  <  param  <  tainted  <  unknown

- `literal`  the value is a string literal in the source;
- `param`    the value comes from a function parameter, so it is reachable from
             the crate's public API (the paper's Q2 criterion);
- `tainted`  the value can be influenced outside the crate: argv, env, stdin,
             file contents, sockets, the working directory;
- `unknown`  anything the shallow analysis cannot see. `unknown` must never
             produce a finding: precision comes from refusing to guess.

Deliberately shallow: intra-procedural, one `let` chain bounded by depth 3, no
interprocedural propagation, no SMT. Guards are recognised with the same
granularity: a guard only counts if it appears *before* the call inside the
same function and mentions the same identifier.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from inventory import find_calls, find_matching, mask_source

LITERAL = "literal"
PARAM = "param"
TAINTED = "tainted"
TRUSTED = "trusted"
UNKNOWN = "unknown"

#: Environment variables that Cargo itself sets. They are dynamic values but
#: not attacker-controlled: a path under OUT_DIR or CARGO_MANIFEST_DIR is the
#: intended build-script behaviour, not the paper's build-time attack.
_TRUSTED_ENV = {
    "OUT_DIR",
    "CARGO_MANIFEST_DIR",
    "CARGO_MANIFEST_PATH",
    "CARGO_TARGET_DIR",
    "TARGET",
    "HOST",
    "PROFILE",
    "OPT_LEVEL",
    "DEBUG",
    "NUM_JOBS",
}
_TRUSTED_PREFIX = ("CARGO_PKG_", "CARGO_CFG_", "CARGO_BIN_EXE_", "CARGO_FEATURE_")

#: Taint sources: (regex, short name). Order matters only for the message.
_TAINT_SOURCES: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"\benv\s*::\s*var(?:_os)?\b"), "env"),
    (re.compile(r"\benv\s*::\s*args(?:_os)?\b"), "argv"),
    (re.compile(r"(?<![\w.:])args\s*\(\s*\)"), "argv"),
    (re.compile(r"\bstdin\s*\(\s*\)"), "stdin"),
    (re.compile(r"\bread_line\b|\bread_to_end\b"), "stdin"),
    (re.compile(r"\bread_to_string\b|\bread_dir\b|\bread_link\b"), "filesystem"),
    (re.compile(r"\bTcpStream\b|\bTcpListener\b|\bUdpSocket\b"), "network"),
    (re.compile(r"\bcurrent_dir\s*\(\s*\)"), "cwd"),
]


@dataclass(frozen=True)
class Prov:
    kind: str
    detail: str = ""
    value: str | None = None

    def is_literal(self) -> bool:
        return self.kind == LITERAL

    def is_dynamic(self) -> bool:
        """True for values a caller can influence (param or tainted)."""
        return self.kind in (PARAM, TAINTED)

    def is_trusted(self) -> bool:
        """True for Cargo-provided values (OUT_DIR and friends)."""
        return self.kind == TRUSTED


@dataclass
class FnFacts:
    name: str
    is_pub: bool
    start: int  # offset of the `pub`/`fn` token
    body_start: int
    body_end: int
    params: dict[str, str] = field(default_factory=dict)
    bindings: dict[str, str] = field(default_factory=dict)


# --------------------------------------------------------------- functions ---

_FN_HEAD = re.compile(
    r"(?m)^[ \t]*(?P<vis>pub(?:\s*\([^)]*\))?)?[ \t]*"
    r"(?:(?:const|async|unsafe|extern[ \t]+\"[^\"]*\")[ \t]+)*"
    r"fn[ \t]+(?P<name>[A-Za-z_]\w*)[ \t]*(?:<[^;{}]*>)?[ \t]*\("
)
_LET = re.compile(r"\blet\s+(?:mut\s+)?([A-Za-z_]\w*)\s*(?::[^=;{}]*)?=\s*")


def parse_fns(src: str, mask: str | None = None) -> list[FnFacts]:
    """All function definitions with a body, sorted by body offset."""
    mask = mask if mask is not None else mask_source(src)
    out: list[FnFacts] = []
    for m in _FN_HEAD.finditer(mask):
        open_p = m.end() - 1
        close_p = find_matching(mask, open_p, "(", ")")
        if close_p is None:
            continue
        body = _find_body(mask, close_p + 1)
        if body is None:
            continue
        close_b = find_matching(mask, body)
        if close_b is None:
            continue
        out.append(
            FnFacts(
                name=m.group("name"),
                is_pub=bool(m.group("vis")),
                start=m.start(),
                body_start=body + 1,
                body_end=close_b,
                params=_parse_params(src[open_p + 1 : close_p]),
                bindings=_parse_bindings(src, mask, body + 1, close_b),
            )
        )
    out.sort(key=lambda f: f.body_start)
    return out


def _find_body(mask: str, start: int) -> int | None:
    depth = 0
    for i in range(start, len(mask)):
        c = mask[i]
        if c in "([":
            depth += 1
        elif c in ")]":
            depth -= 1
        elif c == ";" and depth == 0:
            return None
        elif c == "{" and depth == 0:
            return i
    return None


def fn_at(fns: list[FnFacts], off: int) -> FnFacts | None:
    """Innermost function whose body contains `off` (last one wins)."""
    best = None
    for f in fns:
        if f.body_start <= off < f.body_end:
            best = f
    return best


def _split_top(text: str, sep: str = ",") -> list[str]:
    out, depth, angle, start = [], 0, 0, 0
    for i, c in enumerate(text):
        if c in "([":
            depth += 1
        elif c in ")]":
            depth -= 1
        elif c == "<":
            angle += 1
        elif c == ">" and angle:
            angle -= 1
        elif c == sep and depth == 0 and angle == 0:
            out.append(text[start:i])
            start = i + 1
    out.append(text[start:])
    return out


def _parse_params(text: str) -> dict[str, str]:
    params: dict[str, str] = {}
    for piece in _split_top(text):
        piece = piece.strip()
        if not piece or re.match(r"^(?:&|mut\s+)?self\b", piece):
            continue
        m = re.match(r"(?:mut\s+)?([A-Za-z_]\w*)\s*:\s*(.*)$", piece, re.S)
        if m:
            params[m.group(1)] = m.group(2).strip()
    return params


def _parse_bindings(src: str, mask: str, start: int, end: int) -> dict[str, str]:
    out: dict[str, str] = {}
    for m in _LET.finditer(mask, start, end):
        stop = _scan_expr_end(mask, m.end(), end)
        if stop is None:
            continue
        out[m.group(1)] = src[m.end() : stop].strip()
    return out


def _scan_expr_end(mask: str, start: int, end: int) -> int | None:
    depth = 0
    for i in range(start, end):
        c = mask[i]
        if c in "([{":
            depth += 1
        elif c in ")]}":
            if depth == 0:
                return i
            depth -= 1
        elif c == ";" and depth == 0:
            return i
    return None


# ------------------------------------------------------------- provenance ---

_ADAPTER = re.compile(
    r"\.(?:unwrap|expect|unwrap_or|unwrap_or_else|unwrap_or_default|ok|as_str|"
    r"as_ref|as_mut|to_string|to_owned|to_string_lossy|to_path_buf|into|"
    r"borrow|as_os_str|clone)\s*\(.*\)$",
    re.S,
)
_CTORS = [
    re.compile(r"^(?:PathBuf|Path|OsString|OsStr)\s*::\s*(?:from|from_os_str)\s*\((.*)\)$", re.S),
    re.compile(r"^Path\s*::\s*new\s*\((.*)\)$", re.S),
    re.compile(r"^(?:String|Box|Arc|Rc)\s*::\s*(?:from|new)\s*\((.*)\)$", re.S),
    re.compile(r"^(?:Some|Ok)\s*\((.*)\)$", re.S),
]
_JOINS = re.compile(
    r"^(.*)\.\s*(join|join_with|with_file_name|with_extension|push)\s*\((.*)\)$", re.S
)
_MACRO_JOIN = re.compile(r"^(?:format|concat|format_args|join)!\s*\((.*)\)$", re.S)
_LITERAL = re.compile(r'^(?:b?r(#*)"(.*)"\1|b?"((?:[^"\\]|\\.)*)")$', re.S)


def classify(expr: str, fn: FnFacts | None, _depth: int = 0,
             _seen: frozenset[str] = frozenset()) -> Prov:
    """Coarse provenance of one argument expression."""
    if _depth > 3:
        return Prov(UNKNOWN)
    e = _clean(expr)
    if not e:
        return Prov(UNKNOWN)

    for _ in range(4):  # strip Option/Result adapters, right to left
        m = _ADAPTER.search(e)
        if not m:
            break
        e = e[: m.start()].strip()
    e = _clean(e)
    if not e:
        return Prov(UNKNOWN)

    lit = _literal_value(e)
    if lit is not None:
        return Prov(LITERAL, "", lit)

    for rx in _CTORS:
        m = rx.match(e)
        if m:
            return classify(m.group(1), fn, _depth + 1, _seen)

    parts = _split_sum(e)
    if len(parts) > 1:
        return _combine([classify(p, fn, _depth + 1, _seen) for p in parts])

    m = _MACRO_JOIN.match(e)
    if m:
        return _combine([classify(a, fn, _depth + 1, _seen) for a in _split_top(m.group(1))])

    m = _JOINS.match(e)
    if m:
        base = classify(m.group(1), fn, _depth + 1, _seen)
        arg = classify(m.group(3), fn, _depth + 1, _seen)
        if arg.is_literal() and arg.value and arg.value[:1] in ("/", "\\"):
            # an absolute component discards the base entirely
            return Prov(LITERAL, "", arg.value)
        if base.is_trusted() and arg.is_literal():
            return Prov(TRUSTED, base.detail)
        if base.kind == TAINTED or arg.kind == TAINTED:
            detail = base.detail if base.kind == TAINTED else arg.detail
            return Prov(TAINTED, detail or "path")
        if base.kind == PARAM or arg.kind == PARAM:
            return Prov(PARAM, base.detail if base.kind == PARAM else arg.detail)
        if base.is_literal() and arg.is_literal():
            return Prov(LITERAL, "", None)
        return Prov(UNKNOWN)

    m = re.match(r'^env\s*::\s*var(?:_os)?\s*\(\s*"([^"]+)"', e)
    if m and (m.group(1) in _TRUSTED_ENV or m.group(1).startswith(_TRUSTED_PREFIX)):
        return Prov(TRUSTED, m.group(1))

    for rx, name in _TAINT_SOURCES:
        if rx.search(e):
            return Prov(TAINTED, name)

    if re.fullmatch(r"self\s*\.\s*[A-Za-z_]\w*", e):
        return Prov(PARAM, "self")

    # A field of a local value (`cmd.bin`, `self.config.program`) is not a
    # literal the analysis can see. Treating it as "caller-determined" is what
    # catches `Command::new(&decomp_cmd.bin)` (RUSTSEC-2021-0071) and
    # `Command::new(interpreter)` shapes without guessing a value.
    m = re.fullmatch(r"[A-Za-z_]\w*(?:\s*\.\s*[A-Za-z_]\w*)+", e)
    if m:
        root = re.split(r"\s*\.\s*", e)[0]
        if root == "self" or (fn is not None and (root in fn.params or root in fn.bindings)):
            return Prov(PARAM, e)

    if re.fullmatch(r"[A-Za-z_]\w*", e) and fn is not None:
        if e in fn.bindings and e not in _seen:
            return classify(fn.bindings[e], fn, _depth + 1, _seen | {e})
        if e in fn.params:
            return Prov(PARAM, e)
        return Prov(PARAM, e) if e == "self" else Prov(UNKNOWN)

    return Prov(UNKNOWN)


def _split_sum(text: str) -> list[str]:
    """Split a top-level `+` concatenation (string building)."""
    out, depth, start = [], 0, 0
    for i, c in enumerate(text):
        if c in "([{":
            depth += 1
        elif c in ")]}":
            depth -= 1
        elif c == "+" and depth == 0:
            out.append(text[start:i])
            start = i + 1
    out.append(text[start:])
    return [p for p in (x.strip() for x in out) if p]


def _combine(provs: list[Prov]) -> Prov:
    if provs and all(p.is_trusted() or p.is_literal() for p in provs) and any(
        p.is_trusted() for p in provs
    ):
        return Prov(TRUSTED, next(p.detail for p in provs if p.is_trusted()))
    if any(p.kind == TAINTED for p in provs):
        return Prov(TAINTED, next(p.detail for p in provs if p.kind == TAINTED) or "concat")
    if any(p.kind == PARAM for p in provs):
        return Prov(PARAM, next(p.detail for p in provs if p.kind == PARAM))
    if all(p.is_literal() for p in provs):
        return Prov(LITERAL, "", None)
    return Prov(UNKNOWN)


def _literal_value(e: str) -> str | None:
    m = _LITERAL.match(e)
    if not m:
        return None
    if m.group(2) is not None:  # raw string
        return m.group(2)
    return m.group(3).replace(r"\\", "\\").replace(r"\"", '"')


def _clean(e: str) -> str:
    e = e.strip()
    changed = True
    while changed:
        changed = False
        while e.endswith("?"):
            e = e[:-1].strip()
        while e.startswith("(") and _matching_in(e, 0) == len(e) - 1:
            e = e[1:-1].strip()
            changed = True
        for pref in ("&mut ", "& ", "mut ", "*const ", "*mut "):
            if e.startswith(pref):
                e = e[len(pref) :].strip()
                changed = True
                break
        else:
            if e.startswith("&"):
                e = e[1:].strip()
                changed = True
    return e


def _matching_in(text: str, open_idx: int) -> int | None:
    depth = 0
    for i in range(open_idx, len(text)):
        if text[i] == "(":
            depth += 1
        elif text[i] == ")":
            depth -= 1
            if depth == 0:
                return i
    return None


# ----------------------------------------------------------------- guards ---

def guards_for(mask: str, expr: str, body_start: int, call_start: int) -> list[str]:
    """Validation evidence appearing before the call in the same function.

    Returns short names, e.g. ["starts_with:path"], or [] when unvalidated.
    Only text *before* the call counts: a check after a sink is not a guard.
    """
    pre = mask[body_start:call_start]
    ids = set(re.findall(r"[A-Za-z_]\w*", expr))
    out: list[str] = []

    if re.search(r"\.\s*file_name\s*\(", expr):
        out.append("file_name")
    if re.search(r"\.\s*canonicalize\s*\(", pre) and "starts_with" in pre:
        out.append("canonicalize")
    for m in re.finditer(r"([A-Za-z_]\w*)\s*\.\s*starts_with\s*\(", pre):
        if m.group(1) in ids:
            out.append(f"starts_with:{m.group(1)}")
    if re.search(r"\.\s*components\s*\(\s*\)", pre) and (
        "ParentDir" in pre or "RootDir" in pre
    ):
        out.append("components")
    for m in re.finditer(r"matches!\s*\(\s*([A-Za-z_]\w*)", pre):
        if m.group(1) in ids:
            out.append("matches")
    for m in re.finditer(r"\bmatch\s+([A-Za-z_]\w*)\s*[{(]", pre):
        if m.group(1) in ids:
            out.append("match")
    return out


def stmt_start(mask: str, off: int) -> int:
    """Offset just after the previous statement/block boundary."""
    i = off - 1
    while i >= 0 and mask[i] not in ";{}":
        i -= 1
    return i + 1


def find_all_calls(mask: str) -> list:
    return find_calls(mask, 0, len(mask))
