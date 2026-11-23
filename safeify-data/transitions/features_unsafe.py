"""Hand-built features for classifying an unsafe-code site.

The snippet alone says little; what it *does* says more: which unsafe API it
calls, whether it sits on an FFI boundary, whether it reinterprets pointers,
and whether the fingerprint is a manual length/initialisation hack. These are
the signals a Rust reviewer uses to decide whether a safe alternative exists.

`extract(row)` returns a dict of numeric/binary features plus the API label.
"""

from __future__ import annotations

import re

API_PATTERNS = {
    "set_len": r"\bset_len\s*\(",
    "get_unchecked": r"\bget_unchecked(?:_mut)?\s*\(",
    "from_raw_parts": r"\bfrom_raw_parts(?:_mut)?\s*\(",
    "box_from_raw": r"\bBox::from_raw\s*\(",
    "vec_from_raw_parts": r"\bVec::from_raw_parts\s*\(",
    "cstr_from_ptr": r"\bCStr::from_ptr\s*\(",
    "cstring_from_raw": r"\bCString::from_raw\s*\(",
    "transmute": r"\btransmute(?:_copy)?\b",
    "ptr_read": r"\bptr::read\s*\(",
    "ptr_write": r"\bptr::write(?:_bytes)?\s*\(",
    "ptr_copy": r"\bptr::copy(?:_nonoverlapping)?\s*\(",
    "zeroed": r"\b(?:mem::)?zeroed\s*\(",
    "uninitialized": r"\buninitialized\s*\(",
    "assume_init": r"\bassume_init\b",
    "offset_from": r"\boffset_from\s*\(",
    "pin_new_unchecked": r"\bPin::new_unchecked\b",
    "drop_in_place": r"\bdrop_in_place\s*\(",
    "from_raw": r"\b(?:Rc|Arc)::from_raw\s*\(",
}

STRUCT_PATTERNS = {
    "ffi_extern_c": r'extern\s+"C"',
    "no_mangle": r"#\[no_mangle\]",
    "unsafe_fn": r"\bunsafe\s+fn\b",
    "unsafe_impl": r"\bunsafe\s+impl\b",
    "unsafe_block": r"\bunsafe\s*\{",
    "repr_c": r"#\[repr\(",
    "raw_mut_cast": r"\bas\s+\*mut\b",
    "raw_const_cast": r"\bas\s+\*const\b",
    "ptr_type": r"\*\s*(?:mut|const)\s+\w",
    "raw_deref": r"&\s*(?:mut\s+)?\*",
    "safety_comment": r"(?i)safety",
    "mem_forget": r"\b(?:std::)?mem::forget\b",
    "manually_drop": r"\bManuallyDrop\b",
    "slice_index": r"\w+\s*\[[^\]]+\]",
    "checked_api": r"\b(?:\.get\s*\(|\.get_mut\s*\(|copy_from_slice|from_utf8|try_into)\b",
    "binary_op_arith": r"[+\-*]\s*\w+",
}


def _flags(text: str, patterns: dict[str, str]) -> dict[str, int]:
    return {name: int(bool(re.search(pat, text))) for name, pat in patterns.items()}


def extract(row: dict) -> dict:
    text = row.get("old_snippet") or ""
    api = row.get("api_guess") or "unknown"
    feats = {f"api_{k}": v for k, v in _flags(text, API_PATTERNS).items()}
    feats.update(_flags(text, STRUCT_PATTERNS))
    feats["api_guess"] = api
    feats["n_unsafe_blocks"] = len(re.findall(r"\bunsafe\s*\{", text))
    feats["n_unsafe_fns"] = len(re.findall(r"\bunsafe\s+fn\b", text))
    feats["chars"] = len(text)
    feats["lines"] = text.count("\n") + 1
    feats["idents"] = len(set(re.findall(r"[A-Za-z_][A-Za-z0-9_]*", text)))
    feats["n_api_hits"] = sum(v for k, v in feats.items() if k.startswith("api_") and k != "api_guess")
    return feats


FEATURE_NAMES = None  # filled on first use by feature_matrix


def feature_matrix(rows: list[dict]):
    """Return (numeric matrix, api labels) with a stable feature order."""
    global FEATURE_NAMES
    extracted = [extract(r) for r in rows]
    if FEATURE_NAMES is None:
        FEATURE_NAMES = sorted(k for k in extracted[0] if k != "api_guess")
    import numpy as np
    matrix = np.asarray([[e[k] for k in FEATURE_NAMES] for e in extracted], dtype=float)
    return matrix, [e["api_guess"] for e in extracted]


if __name__ == "__main__":
    row = {"old_snippet": "unsafe { out.set_len(n) }", "api_guess": "set_len"}
    f = extract(row)
    assert f["api_set_len"] == 1 and f["unsafe_block"] == 1
    assert f["lines"] == 1 and f["api_guess"] == "set_len"
    ffi = extract({"old_snippet": 'extern "C" { fn f(); } unsafe { f() }', "api_guess": "unknown"})
    assert ffi["ffi_extern_c"] == 1 and ffi["api_set_len"] == 0
    print("features ok:", len(f), "features")
