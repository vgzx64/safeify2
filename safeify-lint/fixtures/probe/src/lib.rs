use std::process::Command;

pub fn write_home(p: &str) {
    std::fs::write(p, "x").unwrap();
}

pub fn read_env() -> String {
    std::env::var("HOME").unwrap_or_default()
}

pub fn run_ls() {
    Command::new("ls").status().unwrap();
}

pub fn open_path() -> std::io::Result<std::fs::File> {
    std::fs::File::open("/etc/passwd")
}
