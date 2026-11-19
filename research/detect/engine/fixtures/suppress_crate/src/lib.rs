//! Crate-level suppression: every rule allowed from the crate root.
#![allow(safeify::exec_basename)]

use std::process::Command;

pub fn suppressed() {
    Command::new("ls").status().unwrap();
}
