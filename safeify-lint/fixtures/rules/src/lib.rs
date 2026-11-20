//! Rule fixtures. One scenario per comment; line numbers are part of the test.
use std::process::Command;

// Pattern 1: filesystem paths.
pub fn special_path() {
    std::fs::write("/proc/self/mem", b"x").unwrap();
    std::fs::write("/etc/passwd", "x").unwrap();
}

pub fn traversal() {
    std::fs::write("/tmp/../etc/shadow", "x").unwrap();
}

pub fn caller_path(p: &str) {
    std::fs::write(p, "x").unwrap();
}

pub fn guarded_path(p: &str) {
    let canonical = std::fs::canonicalize(p).unwrap();
    if canonical.starts_with("/srv/data") {
        std::fs::write(p, "x").unwrap();
    }
    std::fs::write(p, "y").unwrap();
}

// Pattern 2: command execution.
pub fn exec_basename() {
    Command::new("ls").status().unwrap();
}

pub fn exec_absolute() {
    Command::new("/bin/ls").status().unwrap();
}

pub fn exec_param(p: &str) {
    Command::new(p).status().unwrap();
}

pub fn exec_shell(p: &str) {
    Command::new("bash").arg(p).status().unwrap();
}

pub fn exec_dropper() {
    std::fs::write("/tmp/payload", "x").unwrap();
    Command::new("/tmp/payload").status().unwrap();
}

// Pattern 5: environment variables.
pub fn env_set() {
    std::env::set_var("LD_PRELOAD", "/tmp/inject.so");
}

pub fn env_get() -> Option<String> {
    std::env::var("PATH").ok()
}

pub fn env_safe() {
    std::env::set_var("MY_UNRELATED_VAR", "1");
}

pub fn dir_entry_name(entry: std::fs::DirEntry) {
    std::fs::write(std::path::Path::new("/tmp").join(entry.file_name()), "x").unwrap();
}

// Composition keeps the class of the joined component: a caller-supplied path
// is `param` (info), not `tainted` (warn).
pub fn joined_caller_path(p: &str) {
    let file = std::path::PathBuf::from(p).join("payload");
    std::fs::write(&file, "x").unwrap();
}

// Two literals joined are still one literal path, so the danger table sees it.
pub fn joined_special_path() {
    std::fs::write(std::path::Path::new("/proc/self").join("mem"), b"x").unwrap();
}

// A closure over a literal array is not caller-controlled, so the program name
// stays literal and nothing fires.
pub fn closure_literal_program() {
    ["python", "python3"].iter().for_each(|bin| {
        Command::new(bin).status().unwrap();
    });
}

// A closure over a caller-supplied collection keeps the collection's class.
pub fn closure_param_program(names: &[String]) {
    names.iter().for_each(|name| {
        Command::new(name).status().unwrap();
    });
}

