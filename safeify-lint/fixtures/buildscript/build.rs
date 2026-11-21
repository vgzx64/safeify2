fn main() {
    let out = std::env::var("OUT_DIR").unwrap();
    std::fs::write(std::path::Path::new(&out).join("generated.rs"), "x").unwrap();
    std::fs::write("/tmp/outside_build", "y").unwrap();
    // `target` as a path segment is inside; these substrings are not.
    std::fs::write("targets.txt", "z").unwrap();
    std::fs::write("my_target_dir/x", "z").unwrap();
    std::fs::write("target/generated/x", "z").unwrap();
}
