//! Interprocedural returns: a caller's value reaches a sink through a helper,
//! a method, a two-hop chain, a literal return and a recursion. Line numbers
//! are part of the test contract.
use std::path::{Path, PathBuf};
use std::process::Command;

fn destination(root: &Path, name: &str) -> PathBuf {
    root.join(name)
}

pub fn via_function(root: &Path, name: &str) {
    std::fs::write(destination(root, name), "x").unwrap();
}

fn wrap(root: &Path, name: &str) -> PathBuf {
    destination(root, name)
}

// Two hops: `wrap` -> `destination` -> `Path::join`. The caller's parameter
// still reaches the sink.
pub fn via_chain(root: &Path, name: &str) {
    std::fs::write(wrap(root, name), "x").unwrap();
}

fn kernel_mem() -> &'static str {
    "/proc/self/mem"
}

// The return value is a literal, so the sink sees a literal path.
pub fn via_literal_return() {
    std::fs::write(kernel_mem(), "x").unwrap();
}

struct Layout {
    root: PathBuf,
}

impl Layout {
    fn new(root: PathBuf) -> Self {
        Layout { root }
    }

    fn out(&self, name: &str) -> PathBuf {
        self.root.join(name)
    }
}

// A local method is interpreted, not guessed from its name.
pub fn via_method(layout: &Layout, name: &str) {
    std::fs::write(layout.out(name), "x").unwrap();
}

fn file_only(p: &Path) -> Option<PathBuf> {
    p.file_name().map(PathBuf::from)
}

// `file_name` keeps only the last component, so the value is trusted even
// though the caller's parameter went in: silent.
pub fn guarded_by_callee(p: &Path) {
    if let Some(name) = file_only(p) {
        std::fs::write(name, "x").unwrap();
    }
}

fn recurse(p: &Path) -> PathBuf {
    if p.exists() {
        recurse(p)
    } else {
        PathBuf::from(p)
    }
}

// Recursion is cut, and one `unknown` branch silences the join: silent.
pub fn recursive(p: &Path) {
    std::fs::write(recurse(p), "x").unwrap();
}

fn program(_arg: &str) -> &'static str {
    "bash"
}

// The program name is a constant inside the callee: reported as a basename.
pub fn via_command(arg: &str) {
    Command::new(program(arg)).arg(arg).status().unwrap();
}

// Silence any unused-constructor warning in the fixture itself.
#[allow(dead_code)]
fn build(root: PathBuf) -> Layout {
    Layout::new(root)
}
