"""Hazard taxonomy for unsafe Rust sites.

The mechanism target describes what a fix did; it depends on the maintainer's
choice. This taxonomy describes the *site itself*: why the unsafe operation is
needed. It is a property of the pre-fix snippet, so a classifier can learn it
from the warning alone, and it is what triage needs to decide whether a checked
alternative plausibly exists.

Classes (one primary hazard per site, chosen by specificity order):

  raw_ownership    from_raw_parts, Box/Vec/...::from_raw, into_raw, ManuallyDrop
  manual_capacity  set_len, with_capacity followed by unsafe writes, spare_capacity
  uninit_memory    uninitialized, zeroed, MaybeUninit, assume_init
  reinterpret      transmute, pointer cast to reference
  unchecked_index  get_unchecked, raw pointer offset/add
  ffi_boundary     extern "C", #[no_mangle], extern blocks
  unsafe_trait     unsafe impl / unsafe trait
  unsafe_contract  unsafe fn whose contract the caller must uphold
  unknown          an unsafe block with no recognisable hazard pattern

`classify(text)` returns (hazard, matched pattern or None).
"""

from __future__ import annotations

import re

HAZARDS = {
    "raw_ownership": "raw pointer or raw parts converted into an owned value",
    "manual_capacity": "manual length/capacity management over unsafe memory",
    "raw_memory": "raw pointer read/write/copy/swap over untyped memory",
    "uninit_memory": "uninitialised or zeroed memory / MaybeUninit handling",
    "reinterpret": "type or pointer reinterpretation (transmute, cast to reference)",
    "raw_deref": "dereference or mutation through a raw pointer",
    "unchecked_index": "unchecked indexing or raw pointer arithmetic",
    "ffi_boundary": "FFI boundary (extern \"C\", #[no_mangle], extern block)",
    "unsafe_trait": "unsafe trait/impl that asserts a contract",
    "unsafe_contract": "unsafe fn whose contract the caller must uphold",
    "unsafe_call": "unsafe operation delegated to a call whose contract is not visible here",
    "unknown": "unsafe operation without a recognisable hazard pattern",
}

# specificity order: earlier classes win when several match
RULES: list[tuple[str, list[str]]] = [
    ("raw_ownership", [
        r"\bfrom_raw_parts(?:_mut)?\s*\(",
        r"\b(?:Box|Vec|String|CString|CStr|Rc|Arc)::from_raw\b",
        r"::into_raw\s*\(",
        r"\bManuallyDrop\b",
    ]),
    ("manual_capacity", [
        r"\bset_len\s*\(",
        r"\bwith_capacity\s*\(",
        r"\bspare_capacity_mut\s*\(",
        r"\bfrom_raw_parts_mut\s*\(",
    ]),
    ("raw_memory", [
        r"\bptr::(?:read|write|write_bytes|copy|copy_nonoverlapping|swap)\b",
        r"\bcopy_nonoverlapping\b",
    ]),
    ("uninit_memory", [
        r"\buninitialized\s*\(",
        r"\b(?:mem::)?zeroed\s*\(",
        r"\bMaybeUninit\b",
        r"\bassume_init\b",
    ]),
    ("reinterpret", [
        r"\btransmute(?:_copy)?\b",
        r"&\s*(?:mut\s+)?\*\s*\(?[\w.\[\]]+\s+as\s+\*(?:const|mut)",
        r"\bfrom_utf8_unchecked\b",
        r"\bfrom_bytes_with_nul_unchecked\b",
        r"\bcast::<[^>]+>",
    ]),
    ("raw_deref", [
        r"&\s*(?:mut\s+)?\*\s*\(?\s*[\w.\[\]]",
        r"\*\s*\(?\s*[\w.\[\]]+\s*\)?\s*=",
        r"\(\s*\*\s*[\w.\[\]]+\s*\)",
    ]),
    ("unchecked_index", [
        r"\bget_unchecked(?:_mut)?\s*\(",
        r"\.(?:add|offset|sub)\s*\(",
    ]),
    ("ffi_boundary", [
        r'extern\s+"C"',
        r"#\[no_mangle\]",
        r"\bextern\s*\{",
        r"\blibc::",
        r"\buse\s+(?:libc|nix|winapi|windows_sys|core::ffi|crate::ffi)\b",
    ]),
    ("unsafe_trait", [
        r"\bunsafe\s+impl\b",
        r"\bunsafe\s+trait\b",
    ]),
    ("unsafe_contract", [
        r"\bunsafe\s+fn\b",
    ]),
]

COMPILED = [(h, [re.compile(p) for p in pats]) for h, pats in RULES]


CALL = re.compile(r"\b[A-Za-z_][\w]*(?:::[A-Za-z_][\w]*)*\s*(?:!\s*)?\(")


def classify(text: str) -> tuple[str, str | None]:
    text = text or ""
    for hazard, patterns in COMPILED:
        for pat in patterns:
            if pat.search(text):
                return hazard, pat.pattern
    if CALL.search(text):
        return "unsafe_call", CALL.pattern
    return "unknown", None


if __name__ == "__main__":
    assert classify("unsafe { out.set_len(n) }")[0] == "manual_capacity"
    assert classify("unsafe { x.get_unchecked(i) }")[0] == "unchecked_index"
    assert classify('extern "C" { fn f(); }') [0] == "ffi_boundary"
    assert classify("unsafe { Box::from_raw(p) }")[0] == "raw_ownership"
    assert classify("unsafe { std::mem::transmute(x) }")[0] == "reinterpret"
    assert classify("unsafe { &mut *p }")[0] == "raw_deref"
    assert classify("unsafe { *p = 1; }")[0] == "raw_deref"
    assert classify("unsafe { ptr::write(p, v) }")[0] == "raw_memory"
    assert classify("pub unsafe fn f(p: *const u8)")[0] == "unsafe_contract"
    assert classify("unsafe { some_wrapper(p) }")[0] == "unsafe_call"
    assert len(HAZARDS) == len(RULES) + 2  # + unsafe_call + unknown
    print("hazard taxonomy ok:", len(HAZARDS), "classes")
