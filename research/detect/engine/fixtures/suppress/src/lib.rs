//! Suppression fixture: attribute, comment directive, and an unsuppressed site.
use std::process::Command;

#[allow(safeify::exec_basename)]
pub fn allowed_by_attr() {
    Command::new("ls").status().unwrap();
}

pub fn allowed_by_comment() {
    // safeify: allow(exec_basename)
    Command::new("ls").status().unwrap();
}

pub fn reported() {
    Command::new("ls").status().unwrap();
}
