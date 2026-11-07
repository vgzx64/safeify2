fn main() {
    assert!(!name.is_null());
    let n = {
        let tmp = unsafe { CStr::from_ptr(name) };
        tmp.to_string_lossy().into_owned()
    };
    let pl = Proplist::from_raw_weak(proplist);

}
