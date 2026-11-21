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
            ("fs_special_path", 7, "deny"),
            // `/tmp/../etc/shadow` normalises outside the prefix it names.
            ("fs_traversal_literal", 12, "warn"),
            // A `pub fn` writing to its caller's path: `info`, not `warn`.
            ("fs_tainted_path", 16, "info"),
            // Guarded by `canonicalize` + `starts_with`: silent (line 22).
            // The same value written again after the `if`: reported.
            ("fs_tainted_path", 24, "info"),
            // A bare program name is resolved through PATH.
            ("exec_basename", 29, "warn"),
            // `/bin/ls` is explicit: silent (line 33).
            // A program name from a parameter.
            ("exec_tainted_cmd", 37, "warn"),
            // `bash` is resolved through PATH *and* receives a caller string.
            ("exec_basename", 41, "warn"),
            ("exec_shell_tainted", 41, "warn"),
            // Written by this function first, then executed.
            ("exec_written_path", 46, "warn"),
            ("env_set_dangerous", 51, "warn"),
            ("env_read_dangerous", 55, "info"),
            // `MY_UNRELATED_VAR` is not dangerous: silent (line 59).
            // `PathBuf::from(p).join("payload")` composes, so the caller's path
            // stays `param`: informational, not a tainted-path warning.
            ("fs_tainted_path", 70, "info"),
            // Joining two literals yields the full literal path, so the danger
            // table sees `/proc/self/mem` built by `Path::new(..).join(..)`.
            ("fs_special_path", 75, "deny"),
            // A closure over a literal array: `bin` is a literal element, not a
            // caller value, so nothing fires (lines 80-84).
            // A closure over a caller-supplied collection keeps its class.
            ("exec_tainted_cmd", 89, "warn"),
            // Another process's memory, not only `/proc/self/mem`.
            ("fs_special_path", 95, "deny"),
            // A Windows drive path is absolute: the write/exec pair is a
            // dropper, and the `..` normalises outside its directory.
            ("exec_written_path", 101, "warn"),
            ("fs_traversal_literal", 105, "warn"),
            // A shell with an `.exe` suffix is still a shell on Windows.
            ("exec_basename", 111, "warn"),
            ("exec_shell_tainted", 111, "warn"),
            // Value-preserving iterator adapters keep argv's taint.
            ("fs_tainted_path", 118, "warn"),
            // `lines()` is a taint-producing stdin API.
            ("fs_tainted_path", 125, "warn"),
        ])
    );
}

#[test]
fn advisory_shapes_fire() {
    // The published-advisory shapes are the regression net for the lattice:
    // each fires on the vulnerable line and the deliberate negative stays
    // silent. RUSTSEC-2022-0058 (`inconceivable`) is out of scope by design.
    assert_eq!(
        analyze("advisories"),
        expected(&[
            // grep-cli 0.1.5: program name is a field written from a caller
            // value two functions away.
            ("exec_tainted_cmd", 18, "warn"),
            // rustdecimal: the executed absolute path was written just before.
            ("exec_written_path", 25, "warn"),
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
fn macro_bodies_and_format_arguments_are_evaluated() {
    // `concat!("a", "b")` collapses to a literal, so nothing fires (line 6).
    // `format!` expands to `must_use({ fmt::format(format_args!(..)) })`; the
    // arguments of the builtin are the caller's expressions, so both formatted
    // sinks are reported (lines 2 and 10).
    assert_eq!(
        analyze("macros"),
        expected(&[
            ("fs_tainted_path", 2, "info"),
            ("exec_tainted_cmd", 10, "warn"),
            ("fs_tainted_path", 15, "info"),
            ("fs_tainted_path", 21, "info"),
            ("fs_tainted_path", 27, "info"),
            ("fs_tainted_path", 43, "info"),
            ("fs_tainted_path", 46, "info"),
            // Implicit capture (`format!("{root}/{name}")`) resolves the same
            // way as a positional argument.
            ("fs_tainted_path", 51, "info"),
        ])
    );
}

#[test]
fn crate_local_calls_are_evaluated_at_the_call_site() {
    // The caller's value reaches the sink through a helper (`destination`), a
    // two-hop chain (`wrap` -> `destination`) and a method (`Layout::out`).
    // Composition keeps it the informational `param` class, so the level is
    // `info`: `join` does not promote a plain parameter to a taint source.
    // The literal return of `kernel_mem` is what the sink sees. `file_only`
    // keeps only `file_name()`, so the guarded write stays silent, and a
    // recursive return is cut to `unknown` (also silent).
    assert_eq!(
        analyze("interproc"),
        expected(&[
            ("fs_tainted_path", 12, "info"),
            ("fs_tainted_path", 22, "info"),
            ("fs_special_path", 31, "deny"),
            ("fs_tainted_path", 50, "info"),
            ("exec_basename", 84, "warn"),
        ])
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
