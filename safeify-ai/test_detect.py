"""Self-contained test suite for safeify-ai (no pytest required).

Run from the repository root:
  python safeify-ai/test_detect.py
"""

from __future__ import annotations

import shutil
import sys
from pathlib import Path

try:
    from . import detect, spec_db, verdict, verify
except ImportError:
    import detect
    import spec_db
    import verdict
    import verify

REPO = Path(__file__).resolve().parents[1]
TESTDATA = REPO / "vendors" / "SafeNet" / "testdata"
SNIPPETS = REPO / "safeify-data" / "synth" / "out" / "snippets"


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

