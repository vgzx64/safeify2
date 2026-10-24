"""Verdict engine: deterministic Y/M/N per unsafe sink.

Taxonomy matches research/synth/splits/kb_verdicts.json:
  Y = replaceable (safe alternative exists, drop the unsafe op)
  M = conditional (replaceability depends on dataflow/guards; may be encapsulated)
  N = irreplaceable (no safe alternative in this frame; encapsulate only)

Principles:
  - Conservative defaults: when a pattern cannot be classified, emit M with a
    low confidence. Never claim Y/N from pattern-level gold without evidence.
  - The unchecked family is uniformly Y (KB: every unchecked API can be
    replaced by keeping the check).
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from spec_db import SpecDB

FAMILY = {
    "get_unchecked": "unchecked", "get_unchecked_mut": "unchecked",
    "unwrap_unchecked": "unchecked",
    "unchecked_add": "checked_arith", "unchecked_mul": "checked_arith",
    "mem::transmute": "transmute", "mem::transmute_copy": "transmute",
    "mem::zeroed": "zeroed",
    "ptr::read": "rawmem", "ptr::write": "rawmem", "ptr::copy": "rawmem",
    "ptr::copy_nonoverlapping": "rawmem", "ptr::write_bytes": "rawmem",
    "ptr::read_volatile": "rawmem", "ptr::write_volatile": "rawmem",
    "ptr::deref": "rawmem",
    "as_ref": "rawref", "as_mut": "rawref",
    "set_len": "vec_len",
    "offset_from": "ptr_arith",
    "Box::from_raw": "reconstitute", "Rc::from_raw": "reconstitute",
    "Arc::from_raw": "reconstitute", "Vec::from_raw_parts": "reconstitute",
    "CString::from_raw": "reconstitute",
    "CStr::from_ptr": "borrow_ffi",
    "NonNull::dangling": "zeroed",
}

_PRIM_TY = re.compile(
    r"^(u8|u16|u32|u64|usize|i8|i16|i32|i64|isize|f32|f64|bool|char)\b")
_PTR_TY = re.compile(r"^\*?(const|mut)\b")
_REF_TY = re.compile(r"^&")


@dataclass
class Verdict:
    v: str  # Y / M / N
    confidence: str  # high / low
    reason: str
    safe_alternative: str | None = None
    encapsulate: bool = False
    pattern_hint: int | None = None  # KB pattern id, only with real evidence
    kb_gold: str | None = None  # gold verdict for (api, pattern_hint), if any
    rules: list[str] = field(default_factory=list)


def _type_of_hover(text: str | None) -> str | None:
    """Best-effort type string from a hover blob (drops `name: ` prefix)."""
    if not text:
        return None
    for line in text.splitlines():
        line = line.strip().strip("`")
        if not line or line.startswith("///"):
            continue
        m = re.match(r"^(?:let\s+|ref\s+)?[A-Za-z_]\w*:\s*(.+)$", line)
        # `owner: &String` (param hover) / `let dest: *mut u8` (let-stmt hover)
        if m:
            line = m.group(1).strip()
        return line
    return None


def _kb(db: SpecDB, api: str, pid: int | None) -> str | None:
    if pid is None:
        return None
    return db.kb_verdicts.get(api, {}).get(str(pid))


def _rules_for_pattern(db: SpecDB, api: str, pid: int | None) -> list[str]:
    return [r.source for r in db.rules_for(api) if r.pattern_id == pid]


def decide(db: SpecDB, api: str, *, call_text: str, args: list[str],
           recv_type: str | None, arg_types: list[str | None],
           ret_type: str | None, guards: list[str],
           signature: str) -> Verdict:
    # Normalize LSP hover blobs ("let dest: *mut u8" -> "*mut u8") once, so
    # every family rule below matches on bare types (bug fix 2026-10-19:
    # reconstitute/borrow_ffi/ptr::read matched raw hover text before).
    recv_type = _type_of_hover(recv_type) if recv_type else recv_type
    ret_type = _type_of_hover(ret_type) if ret_type else ret_type
    arg_types = [_type_of_hover(t) if t else t for t in arg_types]

    fam = FAMILY.get(api, "rawmem")
    rules = [r.source for r in db.rules_for(api)]

    if fam == "unchecked":
        m = re.search(r"(\w+)\.(get_unchecked(?:_mut)?)\((.*)\)\s*$", call_text)
        if api in ("get_unchecked", "get_unchecked_mut") and m:
            recv, idx = m.group(1), m.group(3)
            expr = (f"{recv}[{idx}]" if api == "get_unchecked_mut"
                    else f"{recv}.get({idx})")
            return Verdict("Y", "high",
                           "unchecked family: keep the bounds check (KB: all "
                           "unchecked APIs are replaceable).",
                           safe_alternative=expr, pattern_hint=1,
                           kb_gold=_kb(db, api, 1), rules=rules)
        return Verdict("Y", "high",
                       "unchecked family: keep the bounds/validity check.",
                       safe_alternative="use the checked form "
                                        "(`get`/`[]`/indexing/`+`)",
                       pattern_hint=1, kb_gold=_kb(db, api, 1), rules=rules)

    if fam == "checked_arith":
        alt = "checked_add" if "add" in call_text else "checked_mul"
        return Verdict("Y", "high",
                       "unchecked arithmetic: use `+`/`*` (or checked_*/"
                       "wrapping_* by contract).",
                       safe_alternative=f"a.{alt}(b) or a + b",
                       pattern_hint=1, kb_gold=_kb(db, api, 1), rules=rules)

    if fam == "transmute":
        slots = [recv_type, ret_type, *[a for a in arg_types]]
        # non-empty slots AFTER entry normalization = hover actually resolved
        known = [p for p in (_type_of_hover(t) or "" for t in slots) if p]
        # Y requires src+dst type evidence (>= 2 known slots) and all of them
        # primitive. Bug fix 2026-10-19: `for p in prim if p` used to skip
        # missing types, so a fully evidence-free call matched vacuously and
        # was claimed Y — violating "claims only with real evidence".
        if len(known) >= 2 and all(_PRIM_TY.match(p) for p in known):
            return Verdict("Y", "high",
                           "scalar-to-scalar transmute with known primitive "
                           "types: `as` cast is the safe form.",
                           safe_alternative="x as T",
                           pattern_hint=1, kb_gold=_kb(db, api, 1), rules=rules)
        return Verdict("M", "low",
                       "transmute of non-scalar/unknown types: replaceability "
                       "depends on pattern (element-wise conversion may "
                       "exist); classify p2/p3 before claiming Y.",
                       encapsulate=True, rules=rules)

    if fam == "rawmem":
        # KB shape grounding (testdata + knowledgebase/ pattern files):
        #   - p1 Y-shape (misuse): a CONCRETE owner value materialised in-frame
        #     and read/copied behind its back (ptr::read(&s) on a local String,
        #     copy(data.as_ptr(),...) on an owned slice, out.set_len + fill).
        #   - p2 N-shape (borrowed): bare `&T`/`&mut T` param with NO concrete
        #     owner in-frame (swap's ptr::read(a), ptr::read(&v[i])) — nothing
        #     to replace with -> M, never Y.
        # So `&T` hover alone never licenses Y: require a concrete ref type
        # (not bare `T`, not `{unknown}`) or an owner-shaped call expression.
        arg_shapes = " ".join(args)
        # Concrete ref: `&T`/`&mut T` with a NON-generic, known pointee
        # (bare `&T`/`&mut T` generics license nothing: nothing exists in-frame
        # to read through instead — KB p2 shape, e.g. swap in testdata).
        concrete_ref = (
            arg_types
            and arg_types[0]
            and _REF_TY.match(arg_types[0].strip())
            and not re.match(
                r"^&\s*(mut\s+)?(T\b|{unknown}|\?)", arg_types[0].strip()
            )
            and args
            and not re.match(r"^[A-Za-z_]\w*$", args[0].strip())
        )
        # Raw-ptr source outside this frame: `*const/*mut {unknown}` hover
        # (FFI-style); in-frame minted raw ptrs flow through `_`/call args.
        # (`&mut T` hover on a bare param is NOT raw evidence — it is the
        # borrowed p2 shape and must not claim N either; it stays M.)
        raw_evidence = (
            arg_types
            and arg_types[0]
            and _PTR_TY.match(arg_types[0].strip())
        )
        # Owner-shaped call expression? KB p1 Y-shape needs a CONCRETE
        # owner materialised in-frame: dotted path, index, or method call on
        # the FIRST argument (bare identifiers are params -> borrowed shape).
        owner_shaped = (
            args
            and re.search(r"[.\[]|\(\)|as_ptr|as_mut_ptr", args[0])
            and not (
                arg_types
                and arg_types[0]
                and _PTR_TY.match(arg_types[0].strip())
            )
        )
        owner_in_args = bool(
            re.search(
                r"\b[A-Za-z_]\w*(?:\.[A-Za-z_]\w*(?:\([^)]*\))?"
                r"|\[[^\]]*\]\.?(?:as_ptr|as_mut_ptr)?\([^)]*\))",
                arg_shapes,
            )
        )
        if (
            api == "ptr::read"
            and (concrete_ref or owner_shaped)
        ):
            return Verdict("Y", "high",
                           "owner/reference is present in this frame "
                           "(KB ptr::read p1 -> Y): clone/read through the "
                           "owner instead.",
                           safe_alternative="owner.clone()",
                           pattern_hint=1, kb_gold=_kb(db, api, 1), rules=rules)
        if api == "ptr::deref" and "null_check" in guards:
            return Verdict("M", "low",
                           "raw deref behind a null check: the check does not "
                           "prove provenance/aliasing; encapsulate.",
                           encapsulate=True, rules=rules)
        if api in ("ptr::copy", "ptr::copy_nonoverlapping") and \
                "len_cap" in guards:
            return Verdict("M", "low",
                           "memcpy-style copy with length math present: "
                           "replaceability needs dataflow (slice "
                           "copy_from_slice may fit); classify before Y.",
                           encapsulate=True, rules=rules)
        return Verdict("M", "low",
                       f"{api}: raw memory op; preconditions "
                       "(provenance/validity/lifetime) must be verified. "
                       "Encapsulate behind a documented unsafe fn, or find "
                       "the owner in-frame (KB p1).",
                       encapsulate=True, rules=rules)

    if fam == "rawref":
        if "owner" in signature or re.search(r":\s*&", signature):
            return Verdict("Y", "high",
                           "owner/ref appears in this frame (KB as_ref p1 -> "
                           "Y): read through the owner directly.",
                           safe_alternative="use the owner reference",
                           pattern_hint=1, kb_gold=_kb(db, api, 1), rules=rules)
        return Verdict("M", "low",
                       "as_ref through a raw pointer without in-frame owner "
                       "evidence; classify pattern before claiming Y.",
                       encapsulate=True, rules=rules)

    if fam == "vec_len":
        return Verdict("M", "low",
                       "set_len exposes uninitialized slots (KB p1/p2 -> M, "
                       "p3 -> N): prefer push/resize; encapsulate with an "
                       "initialization invariant if kept.",
                       safe_alternative="v.push(..) / v.resize(..)",
                       encapsulate=True, rules=rules)

    if fam == "ptr_arith":
        return Verdict("M", "low",
                       "raw pointer arithmetic: replaceability needs "
                       "provenance evidence; slice/window iterators may "
                       "replace it.",
                       encapsulate=True, rules=rules)

    if fam == "reconstitute":
        if arg_types and arg_types[0] and _PTR_TY.match(arg_types[0].strip()):
            return Verdict("N", "high",
                           "raw pointer arrives from outside this frame; no "
                           "owner exists here to reconstruct ownership from "
                           "(KB from_raw p1 -> N).",
                           encapsulate=True, pattern_hint=1,
                           kb_gold=_kb(db, api, 1), rules=rules)
        return Verdict("M", "low",
                       "from_raw* without type evidence: ownership source "
                       "unknown; classify before claiming Y/N.",
                       encapsulate=True, rules=rules)

    if fam == "borrow_ffi":
        if arg_types and arg_types[0] and _PTR_TY.match(arg_types[0].strip()):
            return Verdict("N", "high",
                           "C string pointer comes from FFI (parameter); the "
                           "owner is not in this frame (KB from_ptr p1 -> N).",
                           encapsulate=True, pattern_hint=1,
                           kb_gold=_kb(db, api, 1), rules=rules)
        return Verdict("M", "low",
                       "CStr::from_ptr without evidence: classify pattern.",
                       encapsulate=True, rules=rules)

    if fam == "zeroed":
        return Verdict("M", "low",
                       "zeroed/invalid value creation: validity depends on "
                       "the type; prefer Default or a zeroable derive.",
                       encapsulate=True, rules=rules)

    return Verdict("M", "low", f"unknown family for {api}", rules=rules)


