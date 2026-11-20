fn main() {
    let out = std::env::var("OUT_DIR").unwrap();
    std::fs::write(std::path::Path::new(&out).join("generated.rs"), "x").unwrap();
    std::fs::write("/tmp/outside_build", "y").unwrap();
}
