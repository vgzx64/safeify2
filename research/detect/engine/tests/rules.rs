//! Regression suite for the rule engine.
//!
//! Each fixture is a small crate whose line numbers are part of the contract:
//! the expected set is exact, so a new finding on a fixture is a failure just
//! like a missing one. That is deliberate — the fixtures encode the *designed*
//! behaviour (guarded writes silent, absolute programs silent), not a snapshot
//! of whatever the engine happened to print.

use std::path::PathBuf;
use std::process::Command;

fn analyze(fixture: &str) -> Vec<(String, u64, String)> {
    let root = PathBuf::from(env!("CARGO_MANIFEST_DIR"))
        .join("fixtures")
        .join(fixture);
    let output = Command::new(env!("CARGO_BIN_EXE_safeify-lint"))
        .arg("--crate")
        .arg(&root)
        .output()
        .expect("engine runs");
    assert!(
        output.status.success(),
        "engine failed on {fixture}: {}",
        String::from_utf8_lossy(&output.stderr)
    );
    let rows: Vec<serde_json::Value> =
        serde_json::from_slice(&output.stdout).expect("findings are JSON");
    let mut findings: Vec<(String, u64, String)> = rows
        .iter()
        .map(|row| {
            (
                row["rule"].as_str().unwrap().to_string(),
                row["line"].as_u64().unwrap(),
                row["level"].as_str().unwrap().to_string(),
            )
        })
        .collect();
    findings.sort();
    findings
}

fn expected(rows: &[(&str, u64, &str)]) -> Vec<(String, u64, String)> {
    let mut out: Vec<(String, u64, String)> = rows
        .iter()
        .map(|(rule, line, level)| (rule.to_string(), *line, level.to_string()))
        .collect();
    out.sort();
    out
}

#[test]
fn filesystem_command_and_environment_rules() {
    assert_eq!(
        analyze("rules"),
        expected(&[
            // `/proc/self/mem` is dangerous regardless of who calls it.
            ("fs_special_path", 6, "deny"),
            // `/tmp/../etc/shadow` normalises outside the prefix it names.
            ("fs_traversal_literal", 11, "warn"),
            // A `pub fn` writing to its caller's path: `info`, not `warn`.
            ("fs_tainted_path", 15, "info"),
            // Guarded by `canonicalize` + `starts_with`: silent (line 21).
            // The same value written again after the `if`: reported.
            ("fs_tainted_path", 23, "info"),
            // A bare program name is resolved through PATH.
            ("exec_basename", 28, "warn"),
            // `/bin/ls` is explicit: silent (line 32).
            // A program name from a parameter.
            ("exec_tainted_cmd", 36, "warn"),
            // `bash` is resolved through PATH *and* receives a caller string.
            ("exec_basename", 40, "warn"),
            ("exec_shell_tainted", 40, "warn"),
            // Written by this function first, then executed.
            ("exec_written_path", 45, "warn"),
            ("env_set_dangerous", 50, "warn"),
            ("env_read_dangerous", 54, "info"),
            // `MY_UNRELATED_VAR` is not dangerous: silent (line 58).
        ])
    );
}

#[test]
fn build_script_writes_are_scoped_to_out_dir() {
    assert_eq!(
        analyze("buildscript"),
        expected(&[
            // Path::new(OUT_DIR).join(..) is trusted: silent (line 3).
            ("build_outside_out_dir", 4, "warn"),
        ])
    );
}

#[test]
fn field_initialised_from_out_dir_is_trusted() {
    // `self.out_dir` is written from OUT_DIR, so a write to it is legitimate.
    assert_eq!(
        analyze("fields"),
        expected(&[
            // The setter stores a caller value, so reads are caller-controlled
            // (plain `&str` setter, and the `P: AsRef<Path>` builder form).
            ("fs_tainted_path", 28, "info"),
            ("fs_tainted_path", 46, "info"),
            ("fs_tainted_path", 65, "info"),
        ])
    );
}

#[test]
fn macro_bodies_are_scanned_but_format_arguments_are_a_known_gap() {
    // `concat!("a","b")` collapses to a literal, so nothing fires.
    // `format!(..)` arguments are still not modelled (see engine.md §5c), and
    // the fixture records that: if this test starts failing, the gap closed.
    let findings = analyze("macros");
    assert!(
        findings.iter().all(|(rule, _, _)| rule == "fs_tainted_path"),
        "no exec findings expected while format! arguments are unknown: {findings:?}"
    );
    assert_eq!(
        findings
            .iter()
            .filter(|(_, line, _)| *line == 4 || *line == 13)
            .count(),
        0,
        "format!-based sinks are expected to be missed today"
    );
}

#[test]
fn suppressions_are_resolved_semantically() {
    // `#[allow(safeify::exec_basename)]` and a `// safeify: allow(...)`
    // comment both suppress; the unsuppressed call still reports.
    assert_eq!(
        analyze("suppress"),
        expected(&[("exec_basename", 15, "warn")])
    );
    // A crate-level `#![allow(...)]` applies to every function.
    assert_eq!(analyze("suppress_crate"), expected(&[]));
}
