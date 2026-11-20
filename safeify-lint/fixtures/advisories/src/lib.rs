//! Regression shapes for published advisories. Line numbers are the contract.
use std::process::Command;

// RUSTSEC-2021-0071 (`grep-cli` 0.1.5): the program name is a struct field
// written from a caller value two functions away, so the call site is
// caller-controlled even though the local variable name looks harmless.
pub struct Decompressor {
    bin: std::ffi::OsString,
}

impl Decompressor {
    pub fn new(program: &std::ffi::OsStr) -> Self {
        Self { bin: program.to_os_string() }
    }
}

pub fn run_decompressor(d: &Decompressor) {
    Command::new(&d.bin).status().unwrap();
}

// RUSTSEC-2022-0042 (`rustdecimal`): write a path, then execute it. No
// dangerous-variable table entry identifies the trigger; the shape does.
pub fn dropper(payload: &str) {
    std::fs::write("/tmp/rustdecimal-payload", payload).unwrap();
    Command::new("/tmp/rustdecimal-payload").status().unwrap();
}

// RUSTSEC-2022-0058 (`inconceivable`): the UB lives in macro expansion behind
// a feature flag. Deliberate negative: the linter must stay silent here.
pub fn macro_only() {
    println!("no call to a sink family");
}
