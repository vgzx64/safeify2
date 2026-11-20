fn main() {
    let digits: mem::MaybeUninit<[u8; 32]> = mem::MaybeUninit::uninit();
    // SAFETY: safe, since we never read bytes that weren't written.
    let mut digits = unsafe { digits.assume_init() };
}
