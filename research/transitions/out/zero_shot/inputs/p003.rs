            self.write_buf.advance(n);
        ready!(unsafe { Pin::new_unchecked(&mut self.io).poll_flush(cx) })?;
    pub fn close(&mut self, cx: &mut Context<'_>) -> Poll<Result<(), U::Error>>
        unsafe {
            ready!(Pin::new_unchecked(&mut self.io).poll_flush(cx))?;
            ready!(Pin::new_unchecked(&mut self.io).poll_shutdown(cx))?;
        }
