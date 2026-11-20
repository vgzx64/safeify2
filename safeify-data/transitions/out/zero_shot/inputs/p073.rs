fn main() {
    let buffer: mem::MaybeUninit<[u8; SIZE]> = mem::MaybeUninit::uninit();
    // SAFETY: safe, since we never read bytes that weren't written.
    let mut buffer = unsafe { buffer.assume_init() };
    //let buffer = buffer.as_mut_ptr();
}
