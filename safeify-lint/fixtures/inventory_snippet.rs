// Inventory fixture: the cases the semantic inventory has to get right, each
// on its own line so the test can talk about them.
//
// - `*ptr` derefs a raw pointer, `*r` derefs a reference (must be excluded)
// - `assert!(..is_null())` puts the guard evidence inside a macro expansion
// - `warn!(..)` does not resolve (no `log` dependency), so its argument call is
//   only visible through the parsed-argument fallback
// - `core::ptr::write` is a resolved path call, `ptr::read` is not (no `use`)

unsafe fn load(ptr: *mut u8, r: &u8) -> u8 {
    assert!(!ptr.is_null());
    let a = unsafe { *ptr };
    let b = *r;
    core::ptr::write(ptr, 0);
    warn!("{}", ptr::read(ptr));
    a + b
}
