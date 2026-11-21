pub fn leaked(p: &str) {
    std::fs::write(p, "x").unwrap();
}
