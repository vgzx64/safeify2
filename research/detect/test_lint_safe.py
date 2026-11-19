"""Self-contained tests for the safe-Rust lints (no pytest required).

Run from research/:  python detect/test_lint_safe.py

Positive cases are adaptations of the figures in Hassnain & Stanford,
"Counterexamples in Safe Rust" (ASEW '24); negatives pin the precision
choices (guards, absolute paths, allowlists, suppression).
"""

from __future__ import annotations

import sys

try:
    from . import lint_safe
except ImportError:
    import lint_safe

FIG1 = """
use std::fs::OpenOptions;
use std::io::{Seek, Write};

pub fn write_to_memory(x: *const i32, value: usize) -> Result<(), std::io::Error> {
    let mut file = OpenOptions::new().write(true).open("/proc/self/mem")?;
    file.seek(std::io::SeekFrom::Start(x as u64))?;
    file.write_all(&value.to_ne_bytes())?;
    Ok(())
}
"""

FIG2 = """
use std::fs::OpenOptions;
use std::io::{Seek, Write};

pub fn write_oob(vector: &Vec<i32>, index: usize, element: i32) {
    let mut file = OpenOptions::new().write(true).open("/proc/self/mem").unwrap();
    let buffer_ptr = vector.as_ptr();
    let ind = buffer_ptr.wrapping_add(index);
    file.seek(std::io::SeekFrom::Start(ind as u64)).unwrap();
    file.write_all(&element.to_ne_bytes()).unwrap();
}
"""

FIG3 = """
use std::process::{Command, Stdio};

pub fn write_memory<T: std::fmt::Display>(x: *const T, value: T) -> Result<(), std::io::Error> {
    let pid = std::process::id();
    let address = x as usize;
    let mut child = Command::new("gdb")
        .arg("--pid")
        .arg(pid.to_string())
        .stdin(Stdio::piped())
        .spawn()?;
    Ok(())
}
"""

FIG6_BUILD = """
use std::fs::{self, OpenOptions};
use std::io::Write;
use std::process::Command;

fn main() {
    let mut file = OpenOptions::new()
        .append(true)
        .create(true)
        .open("cargo.rs")
        .unwrap();
    writeln!(file, "{}", rust_code).unwrap();
    Command::new("rustc").arg("cargo.rs").status().unwrap();
    fs::remove_file("cargo.rs").unwrap();
    fs::rename(script_file_name, &script_path).unwrap();
}
"""

FIG7 = """
use std::env;
use std::process::Command;

fn main() {
    env::set_var(
        "PATH",
        "/tmp/malicious_bin:".to_owned() + &env::var("PATH").unwrap(),
    );
    let output = Command::new("ls").output().expect("Failed to execute command");
}
"""

HARMLESS_LITERAL = """
use std::fs::File;

pub fn dump() -> std::io::Result<()> {
    let out = File::open("/tmp/out.txt")?;
    Ok(())
}
"""

GUARDED = """
use std::fs::File;
use std::path::Path;

pub fn safe_open(root: &Path, user: &str) -> std::io::Result<()> {
    let path = root.join(user);
    if !path.starts_with(root) {
        return Err(std::io::ErrorKind::PermissionDenied.into());
    }
    std::fs::write(path, b"")?;
    Ok(())
}
"""

ABS_CMD = """
use std::process::Command;

pub fn run() -> std::process::ExitStatus {
    Command::new("/usr/bin/ls").status().unwrap()
}
"""

ALLOWLISTED = """
use std::process::Command;

pub fn run(name: &str) -> std::process::ExitStatus {
    if !matches!(name, "ls" | "cat") {
        panic!("refused");
    }
    Command::new(name).status().unwrap()
}
"""

SHELL_TAINTED = """
use std::process::Command;

pub fn run(cmd: &str) {
    Command::new("sh").arg("-c").arg(cmd).status().unwrap();
}
"""

SUPPRESSED_COMMENT = """
use std::fs::File;

pub fn read_mem() -> std::io::Result<()> {
    // nirm: allow(fs_special_path)
    let f = File::open("/proc/self/mem")?;
    Ok(())
}
"""

SUPPRESSED_ATTR = """
use std::process::Command;

#[allow(nirm::exec_basename)]
pub fn spawn() {
    Command::new("git").status().unwrap();
}
"""

PRIVATE_TAINTED = """
use std::fs::File;

fn save_user(p: &str) {
    let _ = std::fs::write(p, b"x");
}
"""

TAINT_JOIN = """
pub fn write_home(name: &str) -> std::io::Result<()> {
    let home = std::env::var("HOME").unwrap();
    std::fs::write(home.clone() + "/" + name, b"")
}
"""

READ_TAINTED = """
pub fn read_any(p: &str) -> std::io::Result<String> {
    std::fs::read_to_string(p)
}
"""

BUILD_OUT_DIR = """
use std::fs::File;
use std::io::Write;

fn main() {
    let out_dir = std::env::var("OUT_DIR").unwrap();
    let mut f = File::create(std::path::Path::new(&out_dir).join("version.rs")).unwrap();
    writeln!(f, "pub const V: &str = \"1\";").unwrap();
}
"""

BUILD_MANIFEST_WRITE = """
use std::fs;

fn main() {
    let src = std::path::PathBuf::from(std::env::var("CARGO_MANIFEST_DIR").unwrap());
    let build = src.join("arrayfire").join("build");
    let _ = fs::create_dir(&build);
}
"""

WINDOWS_DEVICE = """
use std::fs::File;

pub fn poke() -> std::io::Result<File> {
    File::open(r"\\\\.\\PhysicalMemory")
}
"""

PATH_NEW = """
use std::fs::File;
use std::path::Path;

pub fn poke() -> std::io::Result<File> {
    File::open(Path::new("/proc/self/mem"))
}
"""

TRAVERSAL = """
use std::fs::File;

pub fn poke() -> std::io::Result<File> {
    File::open("/tmp/../etc/passwd")
}
"""

TEMPLATED_CMD = """
use std::process::Command;

pub fn run(tool: &str) {
    let _ = Command::new(format!("{}", tool)).status();
}
"""

RELATIVE_DOTDOT = """
use std::fs::File;

pub fn cert() -> std::io::Result<File> {
    File::open("../tests/cert.pem")
}
"""

PROC_SYS_READ = """
pub fn ostype() -> String {
    std::fs::read_to_string("/proc/sys/kernel/ostype").unwrap()
}
"""

PROC_SYS_WRITE = """
pub fn panic_on_oops() -> std::io::Result<()> {
    std::fs::write("/proc/sys/kernel/panic_on_oops", b"1")
}
"""

PUB_PARAM_PATH = """
pub fn write_any(p: &str) -> std::io::Result<()> {
    std::fs::write(p, b"")
}
"""


DANGER_CASES = [
    ("/proc/self/mem", "proc_mem"),
    ("/proc/1234/mem", "proc_mem"),
    ("/proc/kcore", "kernel_mem"),
    ("/dev/mem", "device_mem"),
    ("/proc/1/maps", "proc_maps"),
    ("/etc/ld.so.preload", "preload"),
    (r"\\.\\PhysicalMemory", "windows_device"),
    ("/proc/sys/kernel/panic", "kernel_config"),
    ("/tmp/../etc/passwd", "dotdot"),
    ("../tests/cert.pem", None),
    ("/tmp/out.txt", None),
]

DROPPER = """
pub fn update(url: &str) {
    let payload = reqwest::blocking::get(url).unwrap();
    std::fs::write("/tmp/updater.bin", &payload).unwrap();
    std::process::Command::new("/tmp/updater.bin").spawn().unwrap();
}
"""

WRITTEN_ELSEWHERE_EXEC = """
pub fn helper() {
    std::fs::write("/tmp/helper.bin", b"#!/bin/sh\n").unwrap();
    std::process::Command::new("/tmp/other.bin").status().unwrap();
}
"""


def _rules(src: str, path: str = "case.rs", edition: int | None = None):
    findings = lint_safe.lint_source(src, path=path, edition=edition)
    return {(f.rule, f.level) for f in findings}


def _names(src: str, path: str = "case.rs", edition: int | None = None) -> set[str]:
    return {f.rule for f in lint_safe.lint_source(src, path=path, edition=edition)}


CASES = [
    # (name, source, filename, {rule: level}, forbidden rules)
    ("fig1 proc/self/mem literal", FIG1, "fig1.rs",
     {"fs_special_path": "deny"}, {"fs_tainted_path"}),
    ("fig2 out-of-bounds via proc mem", FIG2, "fig2.rs",
     {"fs_special_path": "deny"}, set()),
    ("fig3 gdb by basename", FIG3, "fig3.rs",
     {"exec_basename": "warn"}, set()),
    ("fig6 build.rs writes and rustc", FIG6_BUILD, "build.rs",
     {"exec_basename": "warn", "build_outside_out_dir": "warn"}, set()),
    ("fig7 PATH rewrite + ls", FIG7, "fig7.rs",
     {"env_set_dangerous": "warn", "exec_basename": "info"}, set()),
    ("harmless literal path", HARMLESS_LITERAL, "ok.rs", {}, {"fs_special_path"}),
    ("guarded tainted path", GUARDED, "ok.rs", {}, {"fs_tainted_path"}),
    ("absolute command path", ABS_CMD, "ok.rs", {}, {"exec_basename"}),
    ("allowlisted command", ALLOWLISTED, "ok.rs", {}, {"exec_tainted_cmd"}),
    ("shell with tainted arg", SHELL_TAINTED, "sh.rs",
     {"exec_shell_tainted": "warn"}, set()),
    ("comment suppression", SUPPRESSED_COMMENT, "ok.rs", {}, {"fs_special_path"}),
    ("attribute suppression", SUPPRESSED_ATTR, "ok.rs", {}, {"exec_basename"}),
    ("private fn demoted to info", PRIVATE_TAINTED, "ok.rs",
     {"fs_tainted_path": "info"}, set()),
    ("env taint reaches path sink", TAINT_JOIN, "ok.rs",
     {"fs_tainted_path": "warn"}, set()),
    ("windows device namespace", WINDOWS_DEVICE, "win.rs",
     {"fs_special_path": "deny"}, set()),
    ("Path::new literal", PATH_NEW, "ok.rs",
     {"fs_special_path": "deny"}, set()),
    ("dotdot traversal literal", TRAVERSAL, "ok.rs",
     {"fs_traversal_literal": "warn"}, set()),
    ("format! tainted command", TEMPLATED_CMD, "ok.rs",
     {"exec_tainted_cmd": "warn"}, set()),
    ("relative ../ literal is not traversal", RELATIVE_DOTDOT, "ok.rs",
     {}, {"fs_traversal_literal"}),
    ("reading /proc/sys is routine", PROC_SYS_READ, "ok.rs",
     {}, {"fs_special_path"}),
    ("writing /proc/sys is the attack", PROC_SYS_WRITE, "ok.rs",
     {"fs_special_path": "warn"}, set()),
    ("pub fn taking a path is info only", PUB_PARAM_PATH, "ok.rs",
     {"fs_tainted_path": "info"}, set()),
    ("reading a caller path is not the pattern", READ_TAINTED, "ok.rs",
     {}, {"fs_tainted_path"}),
    ("build.rs OUT_DIR binding is fine", BUILD_OUT_DIR, "build.rs",
     {}, {"build_outside_out_dir"}),
    ("build.rs writing into the crate is not", BUILD_MANIFEST_WRITE, "build.rs",
     {"build_outside_out_dir": "warn"}, set()),
    ("download, write, exec the written path", DROPPER, "ok.rs",
     {"exec_written_path": "warn"}, set()),
    ("exec a path this fn did not write", WRITTEN_ELSEWHERE_EXEC, "ok.rs",
     {}, {"exec_written_path"}),
]


def main() -> int:
    failures = 0
    for name, src, filename, want, forbid in CASES:
        got = _rules(src, filename)
        got_rules = {r for r, _ in got}
        missing = {r for r in want if r not in got_rules}
        extra = got_rules & forbid
        level_bad = {
            (r, lv)
            for r, lv in want.items()
            if r in got_rules and (r, lv) not in got
        }
        ok = not missing and not extra and not level_bad
        failures += 0 if ok else 1
        status = "PASS" if ok else "FAIL"
        print(f"[{status}] {name}")
        if missing:
            print(f"        missing: {sorted(missing)}; got {sorted(got_rules)}")
        if extra:
            print(f"        unexpected: {sorted(extra)}")
        if level_bad:
            print(f"        wrong level: {sorted(level_bad)}; got {sorted(got)}")

    # edition-aware message
    ed = [f for f in lint_safe.lint_source(FIG7, path="e.rs", edition=2024)
          if f.rule == "env_set_dangerous"]
    if not ed or "edition 2024" not in ed[0].message:
        print("[FAIL] edition 2024 note for env::set_var")
        failures += 1
    else:
        print("[PASS] edition 2024 note for env::set_var")

    # danger table unit checks
    for value, expected in DANGER_CASES:
        hit = lint_safe.danger_path(value)
        good = hit is None if expected is None else (hit is not None and hit[0] == expected)
        if not good:
            print(f"[FAIL] danger_path({value!r}) -> {hit}, want {expected}")
            failures += 1
        else:
            print(f"[PASS] danger_path({value!r}) -> {expected}")
    total = len(CASES) + 1 + len(DANGER_CASES)
    print(f"\n{total - failures}/{total} checks passed")
    return 0 if failures == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
