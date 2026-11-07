fn main() {
        let buf = unsafe {
            // safe because it's within the buffer's limits
            // and we won't be reading uninitialized memory
            std::slice::from_raw_parts_mut(
                self.buf.as_mut_ptr().add(b),
                self.buf.capacity() - b)
        };
        match self.inner.read(buf) {
            Ok(o) => {
                unsafe {
                    // reset the size to include the written portion,
                    // safe because the extra data is initialized
                    self.buf.set_len(b + o);
                }
                Ok(&self.buf[self.consumed..])
            }
            Err(e) => Err(e),
}
