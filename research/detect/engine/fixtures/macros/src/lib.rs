pub fn write_report(root: &str, name: &str) {
    std::fs::write(format!("{}/{}", root, name), "x").unwrap();
}

pub fn literal_concat() {
    std::fs::write(concat!("a", "b"), "y").unwrap();
}

pub fn run_formatted(name: &str) {
    std::process::Command::new(format!("{}", name)).status().unwrap();
}

pub fn prelude_pathbuf(p: &str) {
    let b = PathBuf::from(p);
    std::fs::write(&b, "x").unwrap();
}

pub fn prelude_option(p: &str) {
    let v = Some(p);
    if let Some(path) = v {
        std::fs::write(path, "x").unwrap();
    }
}

pub fn qualified_pathbuf(p: &str) {
    let b = std::path::PathBuf::from(p);
    std::fs::write(&b, "x").unwrap();
}

pub fn ctors(p: &str) {
    let _ = String::from(p);
    let _ = Vec::<u8>::new();
    let _ = std::path::Path::new(p);
    let _ = std::path::PathBuf::from(p);
    let _ = Some(p);
    let _ = Ok::<_, ()>(p);
}

pub fn variants(p: &str) {
    let a = Option::Some(p);
    let b = std::option::Option::Some(p);
    if let Option::Some(x) = a {
        std::fs::write(x, "y").unwrap();
    }
    if let std::option::Option::Some(y) = b {
        std::fs::write(y, "z").unwrap();
    }
}

pub fn implicit_capture(root: &str, name: &str) {
    std::fs::write(format!("{root}/{name}"), "x").unwrap();
}
