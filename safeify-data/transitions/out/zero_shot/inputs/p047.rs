fn main() {
        let mut buf = Vec::with_capacity(BUF_SIZE);
        unsafe {
            buf.set_len(BUF_SIZE);
        }
}
