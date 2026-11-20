fn main() {
    let mut out = Vec::with_capacity(out_buf_len);
    unsafe { out.set_len(out_buf_len) };
    /* This goes against all of Rust's statically verifiable guarantees,
     * but for the below use-case accessing uninitialized memory is ok,
     * as we have other checks to make sure the read memory is not used.
     *
     * The otherwise happening memset slows down the code by a factor of 20-30
     */
    let mut htab: [usize; 1 << HLOG] = unsafe { mem::uninitialized() };
}
