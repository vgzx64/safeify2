"""Self-contained test suite for research/detect (no pytest required).

Run from research/:  python detect/test_detect.py
LSP tests are skipped when rust-analyzer is not on PATH.
"""

from __future__ import annotations

import shutil
import sys
from pathlib import Path

try:
    from . import detect, inventory, spec_db, verdict, verify
except ImportError:
    import detect
    import inventory
    import spec_db
    import verdict
    import verify

REPO = Path(__file__).resolve().parents[2]
TESTDATA = REPO / "vendors" / "SafeNet" / "testdata"
SNIPPETS = REPO / "research" / "synth" / "out" / "snippets"

SAMPLE = """\
fn good() { let s = "// not a comment unsafe {"; }
unsafe fn ext(p: *mut u8) -> u8 {
    unsafe { *p }
}
pub unsafe extern "C" fn ffi(out: &mut *mut u8) {
    let b = 1u8;
    *out = &b as *const u8 as *mut u8;
}
"""


def test_spec_db() -> None:
    db = spec_db.load_spec_db()
    n_rules = sum(len(v) for v in db.rules.values())
    assert n_rules == 42, n_rules
    assert len(db.rules) == 19
    assert db.kb_verdicts["Box::from_raw"]["1"] == "N"
    assert db.match_api("std::ptr::read", False) == "ptr::read"
    assert db.match_api("read", False) is None  # bare `read` must not match
    assert db.match_api("get_unchecked", True) == "get_unchecked"
    assert db.match_api("clone", True) is None
    assert db.match_api("Vec::from_raw_parts", False) == "Vec::from_raw_parts"


def test_mask_and_regions() -> None:
    mask = inventory.mask_source(SAMPLE)
    assert len(mask) == len(SAMPLE)
    regions = inventory.find_unsafe_regions(SAMPLE, mask)
    kinds = sorted((r.kind, r.name) for r in regions)
    assert ("block", None) in kinds
    assert ("fn", "ext") in kinds
    assert ("fn", "ffi") in kinds  # `unsafe extern "C" fn`
    assert len(regions) == 3, regions  # comment/string `unsafe` ignored


def test_calls_and_derefs() -> None:
    mask = inventory.mask_source(SAMPLE)
    regions = inventory.find_unsafe_regions(SAMPLE, mask)
    block = [r for r in regions if r.kind == "block"][0]
    derefs = inventory.find_raw_derefs(mask, block.body_start, block.body_end)
    assert derefs and derefs[0][1] == "*p", derefs
    fn_ffi = [r for r in regions if r.name == "ffi"][0]
    derefs2 = inventory.find_raw_derefs(mask, fn_ffi.body_start, fn_ffi.body_end)
    # only the `*out = ...` assignment target; `as *const u8` is not a deref
    assert all(d[1] == "*out" for d in derefs2), derefs2


def test_verdict_tables() -> None:
    db = spec_db.load_spec_db()
    v = verdict.decide(db, "get_unchecked_mut",
                       call_text="v.get_unchecked_mut(i)", args=["i"],
                       recv_type=None, arg_types=["usize"], ret_type=None,
                       guards=[], signature="fn f(v: &mut Vec<u8>, i: usize)")
    assert (v.v, v.confidence) == ("Y", "high")
    assert v.safe_alternative == "v[i]"
    v = verdict.decide(db, "Box::from_raw", call_text="Box::from_raw(p)",
                       args=["p"], recv_type=None, arg_types=["*mut i32"],
                       ret_type=None, guards=[],
                       signature="fn consume(p: *mut i32) -> i32")
    assert (v.v, v.confidence, v.kb_gold) == ("N", "high", "N")
    v = verdict.decide(db, "ptr::read", call_text="std::ptr::read(&owner.val)",
                       args=["&owner.val"], recv_type=None, arg_types=["&String"],
                       ret_type=None, guards=[],
                       signature="fn dup(owner: &Wrap) -> String")
    assert (v.v, v.kb_gold, v.pattern_hint) == ("Y", "Y", 1)
    v = verdict.decide(db, "ptr::write", call_text="ptr::write(p, x)",
                       args=["p", "x"], recv_type=None, arg_types=[None, None],
                       ret_type=None, guards=[], signature="")
    assert (v.v, v.confidence) == ("M", "low")  # conservative without evidence
    v = verdict.decide(db, "set_len", call_text="v.set_len(n)", args=["n"],
                       recv_type=None, arg_types=[None], ret_type=None,
                       guards=["with_capacity"], signature="fn f() -> Vec<u64>")
    assert v.v == "M" and v.encapsulate


def test_no_lsp_detect() -> None:
    db = spec_db.load_spec_db()
    f = TESTDATA / "ptr::read" / "1-1.rs"
    rep = detect.analyze_file(f, db, None)
    assert rep["unsafe_regions"] == 1
    assert len(rep["sinks"]) == 8, len(rep["sinks"])
    for s in rep["sinks"]:
        assert s["api"] == "ptr::read"
        assert s["verdict"]["v"] in ("Y", "M", "N")


def test_verify() -> None:
    ok, _ = verify.rustc_check("pub fn f() -> u32 { 1 + 2 }\n")
    assert ok
    ok, err = verify.rustc_check("pub fn f() -> u32 { \"x\" }\n")
    assert not ok and "expected" in err


def test_lsp_e2e() -> None:
    if not shutil.which("rust-analyzer"):
        print("  (skip: rust-analyzer not on PATH)")
        return
    db = spec_db.load_spec_db()

    # Sorted, and pinned to pattern 1: `glob` order is filesystem-dependent,
    # and a pattern-2 field-access snippet correctly abstains (M) instead of
    # producing the N this assertion is about.
    f = sorted(SNIPPETS.glob("ptr::read/1-*-unsafe.rs"))[0]
    with detect.Analyzer() as an:
        an.open_file(f)
        rep = detect.analyze_file(f, db, an)
    s = rep["sinks"][0]
    assert s["evidence"]["lsp"], s["evidence"]
    # mod-wrapped synth snippets do not resolve in RA (hover `&{unknown}`):
    # without concrete-type evidence the engine must abstain, never claim Y.
    assert s["verdict"]["v"] == "M", s["verdict"]

    f = sorted(SNIPPETS.glob("Box::from_raw/1-*-unsafe.rs"))[0]
    with detect.Analyzer() as an:
        an.open_file(f)
        rep = detect.analyze_file(f, db, an)
    s = rep["sinks"][0]
    assert s["verdict"]["v"] == "N" and s["verdict"]["kb_gold"] == "N"

    f = sorted(SNIPPETS.glob("ptr::read/1-*-safe.rs"))[0]
    with detect.Analyzer() as an:
        an.open_file(f)
        rep = detect.analyze_file(f, db, an)
    assert rep["sinks"] == [], rep["sinks"]  # safe snippet: no sinks


def main() -> int:
    tests = [(k, v) for k, v in sorted(globals().items())
             if k.startswith("test_") and callable(v)]
    failed = 0
    for name, fn in tests:
        try:
            fn()
            print(f"PASS {name}")
        except Exception as ex:
            failed += 1
            import traceback

            print(f"FAIL {name}: {ex}")
            traceback.print_exc()
    print(f"\n{len(tests) - failed}/{len(tests)} passed")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())

