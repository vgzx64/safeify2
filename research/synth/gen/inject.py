"""Strategy A: counterfactual injection from safe code.

Each family starts from a *safe* Rust source template (seeds/safe/*.rs) and
applies the known inverse of a safe idiom (as -> transmute, from_le_bytes ->
transmute, [] -> get_unchecked, clone -> into_raw/from_raw roundtrip,
literal/default -> zeroed). The unmodified safe render is emitted as the
`-safe.rs` counterpart, so every unsafe snippet ships with a real,
ground-truth replacement (replaceability=Y by construction).

`replace` entries are ($needle, $replacement) template pairs rendered with the
same variant dict as the seed before applying str.replace.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import (OUT_RECORDS_INJ, SYNTH_ROOT, flush_records, render,
                    write_snippet)

SEEDS = os.path.join(SYNTH_ROOT, "seeds", "safe")

FAMILIES = [
    {
        "family": "cast_transmute", "seed": "cast_transmute.rs",
        "api": "mem::transmute", "pattern_id": 1,
        "replaceability": "Y", "verdict": "replaceable", "difficulty": "easy",
        "contract": "Numeric/reference reinterpretation done with transmute where a plain `as` cast is the documented safe idiom (KB pattern: 'misuse, replace with as').",
        "replace": [("$E",
                     "unsafe { std::mem::transmute::<$FROM, $TO>(x) }")],
        "grid": [
            {"FROM": "i32", "TO": "u32", "E": "x as u32", "N": "cast_u32"},
            {"FROM": "u32", "TO": "i32", "E": "x as i32", "N": "cast_i32"},
            {"FROM": "i64", "TO": "u64", "E": "x as u64", "N": "cast_u64"},
            {"FROM": "u64", "TO": "i64", "E": "x as i64", "N": "cast_i64"},
            {"FROM": "f32", "TO": "u32", "E": "x as u32", "N": "cast_bits32"},
            {"FROM": "f64", "TO": "u64", "E": "x as u64", "N": "cast_bits64"},
            {"FROM": "char", "TO": "u32", "E": "x as u32", "N": "cast_codepoint"},
            {"FROM": "&'static i32", "TO": "usize", "E": "x as *const i32 as usize", "N": "cast_addr"},
            {"FROM": "&'static u8", "TO": "usize", "E": "x as *const u8 as usize", "N": "cast_byte_addr"},
        ],
    },
    {
        "family": "bytes_transmute", "seed": "bytes_transmute.rs",
        "api": "mem::transmute", "pattern_id": 2,
        "replaceability": "Y", "verdict": "replaceable", "difficulty": "easy",
        "contract": "Byte-array reinterpreted with transmute where from_le_bytes is the endian-correct safe idiom (KB pattern: 'misuse, replace with safe APIs: from_le_bytes...').",
        "replace": [("$T::from_le_bytes(b)",
                     "unsafe { std::mem::transmute::<[$U; $W], $T>(b) }")],
        "grid": [
            {"T": "u16", "U": "u8", "W": 2, "N": "le_u16"},
            {"T": "u32", "U": "u8", "W": 4, "N": "le_u32"},
            {"T": "u64", "U": "u8", "W": 8, "N": "le_u64"},
        ],
    },
    {
        "family": "slice_unchecked", "seed": "slice_unchecked.rs",
        "api": "get_unchecked", "pattern_id": 1,
        "replaceability": "Y", "verdict": "replaceable", "difficulty": "easy",
        "contract": "Bounds-checked index replaced by get_unchecked; the directly-replaceable 'unchecked' family: drop the unchecked call and keep the check.",
        "replace": [("s[i]", "unsafe { *s.get_unchecked(i) }")],
        "grid": [
            {"T": "u32", "N": "idx_u32"},
            {"T": "i32", "N": "idx_i32"},
            {"T": "u64", "N": "idx_u64"},
            {"T": "f64", "N": "idx_f64"},
        ],
    },
    {
        "family": "rc_roundtrip", "seed": "rc_roundtrip.rs",
        "api": "Rc::from_raw", "pattern_id": 1,
        "replaceability": "Y", "verdict": "replaceable", "difficulty": "easy",
        "contract": "Rc reconstructed from a raw roundtrip where Rc::new/clone already suffices (KB: 'Straightforward: replaceable with Rc::new').",
        "replace": [("let b = a.clone();",
                     "let b = unsafe { Rc::from_raw(Rc::into_raw(a.clone())) };")],
        "grid": [
            {"T": "i32", "LIT": "4", "N": "rc_i32"},
            {"T": "u64", "LIT": "4", "N": "rc_u64"},
            {"T": "f64", "LIT": "4.0", "N": "rc_f64"},
            {"T": "bool", "LIT": "true", "N": "rc_bool"},
        ],
    },
    {
        "family": "zeroed_init", "seed": "zeroed_init.rs",
        "api": "mem::zeroed", "pattern_id": 1,
        "replaceability": "Y", "verdict": "replaceable", "difficulty": "easy",
        "contract": "Zeroed allocation for a primitive/Default type where an eager literal or Default::default() is equivalent (KB: 'function with Rust primitive types -> Y').",
        "replace": [("let n: $T = $INIT;",
                     "let n: $T = unsafe { std::mem::zeroed::<$T>() };")],
        "grid": [
            {"T": "u8", "INIT": "0", "N": "zero_u8"},
            {"T": "u32", "INIT": "0", "N": "zero_u32"},
            {"T": "u64", "INIT": "0", "N": "zero_u64"},
            {"T": "i8", "INIT": "0", "N": "zero_i8"},
            {"T": "i32", "INIT": "0", "N": "zero_i32"},
            {"T": "usize", "INIT": "0", "N": "zero_usize"},
            {"T": "bool", "INIT": "false", "N": "zero_bool"},
            {"T": "f32", "INIT": "0.0", "N": "zero_f32"},
            {"T": "f64", "INIT": "0.0", "N": "zero_f64"},
        ],
    },
]


def inject(safe_text, family, variant):
    """Apply the family's ($needle, $replacement) pairs to rendered safe text."""
    out = safe_text
    for needle_tpl, repl_tpl in family["replace"]:
        needle = render(needle_tpl, variant)
        repl = render(repl_tpl, variant)
        if needle not in out:
            raise ValueError(
                f"{family['family']}: needle {needle!r} not found in seed render")
        out = out.replace(needle, repl)
    return out


def main():
    records = []
    seq = 0
    counts = {"unsafe": 0, "safe": 0}
    for fam in FAMILIES:
        with open(os.path.join(SEEDS, fam["seed"]), encoding="utf-8") as f:
            seed_tpl = f.read()
        base = {
            "source": "counterfactual_injection",
            "api": fam["api"],
            "pattern_id": fam["pattern_id"],
            "replaceability": fam["replaceability"],
            "verdict": fam["verdict"],
            "difficulty": fam["difficulty"],
            "contract": fam["contract"],
            "family": fam["family"],
        }
        for variant in fam["grid"]:
            seq += 1
            safe_text = render(seed_tpl, variant)
            unsafe_text = inject(safe_text, fam, variant)
            unsafe_rec = write_snippet(
                fam["api"], fam["pattern_id"], "unsafe", seq, unsafe_text,
                dict(base, variant=variant), records)
            counts["unsafe"] += 1
            write_snippet(
                fam["api"], fam["pattern_id"], "safe", seq, safe_text,
                dict(base, variant=variant, parent=unsafe_rec["id"]), records)
            counts["safe"] += 1
    flush_records(records, OUT_RECORDS_INJ)
    print(f"inject: {len(FAMILIES)} families -> {counts} "
          f"({sum(counts.values())} files, {OUT_RECORDS_INJ})")


if __name__ == "__main__":
    main()
