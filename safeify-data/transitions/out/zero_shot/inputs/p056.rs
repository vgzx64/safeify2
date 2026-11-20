    pub(super) fn rows_affected(&self) -> usize {
        unsafe {
            let count_char_ptr = PQcmdTuples(self.internal_result.as_ptr());
            let count_bytes = CStr::from_ptr(count_char_ptr).to_bytes();
            // Using from_utf8_unchecked is ok here because, we've set the
            // client encoding to utf8
            let count_str = str::from_utf8_unchecked(count_bytes);
            match count_str {
