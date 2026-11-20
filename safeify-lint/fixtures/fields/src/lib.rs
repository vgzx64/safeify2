//! Field-summary fixture: OUT_DIR-derived field vs caller-derived field.
use std::path::PathBuf;

pub struct Trusted {
    dir: PathBuf,
}

impl Trusted {
    pub fn new() -> Self {
        Trusted { dir: std::env::var_os("OUT_DIR").map(PathBuf::from).unwrap() }
    }

    pub fn install(&self) {
        std::fs::create_dir_all(&self.dir).unwrap();
    }
}

pub struct Caller {
    dir: PathBuf,
}

impl Caller {
    pub fn new(dir: PathBuf) -> Self {
        Caller { dir }
    }

    pub fn install(&self) {
        std::fs::create_dir_all(&self.dir).unwrap();
    }
}

pub struct Setter {
    dir: Option<PathBuf>,
}

impl Setter {
    pub fn new() -> Self {
        Setter { dir: std::env::var_os("OUT_DIR").map(PathBuf::from) }
    }

    pub fn set_dir(&mut self, path: &str) {
        self.dir = Some(PathBuf::from(path));
    }

    pub fn install(&self) {
        std::fs::create_dir_all(self.dir.as_ref().unwrap()).unwrap();
    }
}

pub struct Generic {
    dir: Option<PathBuf>,
}

impl Generic {
    pub fn new() -> Self {
        Generic { dir: std::env::var_os("OUT_DIR").map(PathBuf::from) }
    }

    pub fn out_dir<P: AsRef<std::path::Path>>(&mut self, path: P) -> &mut Self {
        self.dir = Some(path.as_ref().to_path_buf());
        self
    }

    pub fn install(&self) {
        std::fs::create_dir_all(self.dir.as_ref().unwrap()).unwrap();
    }
}
