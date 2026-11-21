//! Rule fixtures. One scenario per comment; line numbers are part of the test.
use std::io::BufRead;
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

// `/proc/<pid>` names another process, not just this one.
pub fn special_pid_path() {
    std::fs::write("/proc/1234/mem", b"x").unwrap();
}

// A Windows drive path is absolute: the dropper pair and traversal see it.
pub fn windows_dropper() {
    std::fs::write("C:\\tmp\\winpayload.exe", b"mz").unwrap();
    Command::new("C:\\tmp\\winpayload.exe").status().unwrap();
}

pub fn windows_traversal() {
    std::fs::write("C:\\tmp\\..\\outside", b"x").unwrap();
}

// A shell with an `.exe` suffix receives the same caller string as `bash`.
pub fn exec_windows_shell() {
    let arg = std::env::var("PROBE_ARG").unwrap();
    Command::new("powershell.exe").arg(arg).status().unwrap();
}

// Value-preserving iterator adapters keep the source's class: argv through
// `nth` is as caller-controlled as the `for` loop over `args()`.
pub fn argv_nth() {
    let arg = std::env::args().nth(1).unwrap();
    std::fs::write(&arg, "x").unwrap();
}

// `lines()` is the value-producing stdin API; `read_line` writes into its
// buffer argument and is not modelled.
pub fn stdin_lines() {
    let line = std::io::stdin().lines().next().unwrap().unwrap();
    std::fs::write(line, "x").unwrap();
}

// `format!` composes taint-dominantly: a trusted prefix does not launder a
// caller-controlled suffix.
pub fn formatted_param(user: &str) {
    let out = std::env::var("OUT_DIR").unwrap();
    let target = format!("{out}/{user}");
    std::fs::write(target, "x").unwrap();
}

// `canonicalize` resolves a path but does not confine it.
pub fn canonical_writes(p: &str) {
    let real = std::fs::canonicalize(p).unwrap();
    std::fs::write(real, "x").unwrap();
}

// `parent` walks up from a caller path; it does not confine either.
pub fn parent_join(p: &std::path::Path) {
    let up = p.parent().unwrap().join("outside");
    std::fs::write(up, "x").unwrap();
}

// A `const`/`static` names the literal it is initialised with.
const MEM_CONST: &str = "/proc/self/mem";
static PAGEMAP_STATIC: &str = "/proc/self/pagemap";

pub fn const_path() {
    std::fs::write(MEM_CONST, "x").unwrap();
}

pub fn static_path() {
    std::fs::write(PAGEMAP_STATIC, "x").unwrap();
}

// `+` concatenates two known literals into the path they spell.
pub fn plus_literal_path() {
    let base = String::from("/etc/ld.so");
    std::fs::write(base + ".preload", "x").unwrap();
}

// A collection's class is the composition of its elements (may-join).
pub fn collection_join() {
    let names = ["trusted.txt".to_string(), std::env::var("PROBE_OUT").unwrap()];
    std::fs::write(&names[1], "x").unwrap();
}

// `if !canon.starts_with(base) { return }` guards the write after it.
pub fn early_return_guard(p: &std::path::Path) {
    let real = std::fs::canonicalize(p).unwrap();
    if !real.starts_with("/srv/data") {
        return;
    }
    std::fs::write(&real, "x").unwrap();
}

// The positive form does not: the write runs when the check failed.
pub fn positive_check_no_guard(p: &std::path::Path) {
    let real = std::fs::canonicalize(p).unwrap();
    if real.starts_with("/srv/data") {
        return;
    }
    std::fs::write(&real, "x").unwrap();
}

// Only a `file_name()` that survives to the argument is a guard:
// `base.join(other.file_name())` keeps the caller-controlled base.
pub fn file_name_on_descendant(base: &std::path::Path, other: &std::path::Path) {
    std::fs::write(base.join(other.file_name().unwrap()), "x").unwrap();
}

pub fn file_name_only(p: &std::path::Path) {
    std::fs::write(p.file_name().unwrap(), "x").unwrap();
}

// The source of `copy`/`rename` is read, not written.
pub fn copy_destination_only(p: &std::path::Path) {
    let out = std::env::var("OUT_DIR").unwrap();
    std::fs::copy(p, &out).ok();
}

pub fn copy_into_caller_path(p: &std::path::Path) {
    std::fs::copy("/etc/hostname", p).ok();
}

// ...but a dangerous literal source is still in the table.
pub fn copy_from_proc_mem() {
    std::fs::copy("/proc/self/mem", "/tmp/copy").unwrap();
}
