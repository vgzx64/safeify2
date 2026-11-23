"""Canonical safe-remediation mechanism taxonomy for the transition corpus.

The binary "replaceable" target proved noisy and not transferable. This is the
replacement target: *which* safe mechanism the fix used to discharge the unsafe
operation. A mechanism is visible in the fix diff (it is not a judgement about
the maintainer), so labels are observable and multi-class.

Fine classes are grouped into families for stable reporting when a fine class
has too few rows.

Usage:
    from mechanism_taxonomy import MECHANISMS, FAMILIES, canon
"""

from __future__ import annotations

# fine class -> (family, one-line definition)
MECHANISMS = {
    "checked_api": ("checked",
        "the operation is replaced by a bounds/validity-checked API that returns "
        "an error or Option instead of UB: get/get_mut, copy_from_slice, "
        "from_utf8, from_bytes_with_nul, try_into, parse, checked_*"),
    "slice_view": ("checked",
        "raw pointer arithmetic, indexing or reinterpretation is replaced by safe "
        "slice/iterator operations: chunks_exact, windows, split_at, iter, "
        "as_slice, to_ne_bytes/from_ne_bytes on slices, zip over slices"),
    "init_memory": ("memory",
        "uninitialized, zeroed or set_len memory is replaced by initialized "
        "memory: vec![0; n], [0; N], Default, MaybeUninit written before "
        "assume_init"),
    "capacity_ops": ("memory",
        "manual length/capacity manipulation is replaced by safe Vec/String "
        "methods: resize, resize_with, truncate, reserve, with_capacity"),
    "safe_wrapper": ("safe_api",
        "the operation is delegated to a safe abstraction that performs the whole "
        "job (a checked wrapper, a safe helper, a std constructor such as "
        "Box/Vec/CString, into()/as_mut(), a backend API)"),
    "interior_mutability": ("ownership",
        "raw-pointer aliasing or unsynchronised mutation is replaced by "
        "Cell/RefCell/Mutex/RwLock/Atomic/ArcSwap or by &mut borrowing"),
    "pin_api": ("ownership",
        "Pin::new_unchecked and friends are replaced by the safe Pin API: "
        "Pin::new, Pin::get_mut, Pin::as_mut, pin! macro"),
    "restructure": ("ownership",
        "the unsafe operation disappears because the data representation or "
        "ownership changes: enum instead of transmute, layout/#[repr] change, a "
        "newtype, taking ownership instead of raw parts"),
    "unnecessary": ("remove",
        "no replacement is needed: the operation was already safe, the unsafe "
        "block or fn qualifier is simply removed (safe_signature), or the code "
        "is deleted and the remaining code is safe"),
    "other": ("remove",
        "a real replacement is shown but it does not fit any class above; "
        "rationale must say why"),
}

FAMILIES = {
    "checked": "bounds/validity checks or pointer-free slice operations",
    "memory": "initialization and capacity handled by safe std methods",
    "safe_api": "delegation to a safe wrapper, helper or constructor",
    "ownership": "aliasing, pinning or data-layout redesign",
    "remove": "unsafe is unnecessary or the class is a residual bucket",
    "retain": "no safe mechanism in this frame; M/N rows",
}

# free-text mechanisms already present in labels_safe.csv -> canonical class
MAP = {
    "checked_index": "checked_api",
    "checked_parser": "checked_api",
    "checked_utf8": "checked_api",
    "copy_from_slice": "checked_api",
    "pointer_arith": "slice_view",
    "slice_iter": "slice_view",
    "zero_init": "init_memory",
    "maybe_uninit": "init_memory",
    "maybeuninit": "init_memory",
    "resize": "capacity_ops",
    "resize_slice": "capacity_ops",
    "truncate": "capacity_ops",
    "safe_helper": "safe_wrapper",
    "safe_slice": "safe_wrapper",
    "owned_vec": "safe_wrapper",
    "option_take": "safe_wrapper",
    "borrow_refcell": "interior_mutability",
    "cell_api": "interior_mutability",
    "pin_api": "pin_api",
    "safe_enum": "restructure",
    "layout_change": "restructure",
    "remove_unnecessary_unsafe": "unnecessary",
    "safe_signature": "unnecessary",
    "unnecessary": "unnecessary",
    "other": "other",
}

RETENTION_CLASSES = {"M": "retain", "N": "retain", "U": "retain"}


def canon(free_text: str) -> str:
    """Map a historical free-text mechanism to a canonical class."""
    return MAP.get((free_text or "").strip().lower(), "other")


def family(mechanism: str) -> str:
    if mechanism == "retain":
        return "retain"
    return MECHANISMS[mechanism][0]


if __name__ == "__main__":
    for mech, (fam, _) in MECHANISMS.items():
        assert fam in FAMILIES, f"{mech} has unknown family {fam}"
    for free, mech in MAP.items():
        assert mech in MECHANISMS, f"{free} maps to unknown {mech}"
    assert canon("checked_index") == "checked_api"
    assert canon("maybe_uninit") == "init_memory"
    assert canon("nonsense") == "other"
    assert family("retain") == "retain"
    assert family("pin_api") == "ownership"
    print("mechanism taxonomy ok:", len(MECHANISMS), "mechanisms,", len(FAMILIES), "families")
