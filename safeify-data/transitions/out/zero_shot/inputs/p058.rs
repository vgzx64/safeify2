fn main() {
        unsafe { 0 != PQgetisnull(self.internal_result.as_ptr(), row_idx, col_idx) }
        let type_oid = unsafe { PQftype(self.internal_result.as_ptr(), col_idx) };
}
