fn main() {
            unsafe {
                let value_ptr =
                    PQgetvalue(self.internal_result.as_ptr(), row_idx, col_idx) as *const u8;
                let num_bytes = PQgetlength(self.internal_result.as_ptr(), row_idx, col_idx);
                Some(slice::from_raw_parts(
                    value_ptr,
                    num_bytes
                        .try_into()
                        .expect("Diesel expects at least a 32 bit operating system"),
}
