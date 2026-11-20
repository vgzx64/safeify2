                self.flags.remove(Flags::READABLE);
            debug_assert!(!self.flags.contains(Flags::EOF));
            let remaining = self.read_buf.capacity() - self.read_buf.len();
                self.read_buf.reserve(HW - remaining)
            let cnt = match unsafe {
                Pin::new_unchecked(&mut self.io).poll_read_buf(cx, &mut self.read_buf)
            } {
                self.flags.insert(Flags::EOF);
            self.flags.insert(Flags::READABLE);
    pub fn flush(&mut self, cx: &mut Context<'_>) -> Poll<Result<(), U::Error>>
        while !self.write_buf.is_empty() {
            log::trace!("writing; remaining={}", self.write_buf.len());
            let n = ready!(unsafe {
                Pin::new_unchecked(&mut self.io).poll_write(cx, &self.write_buf)
            })?;
