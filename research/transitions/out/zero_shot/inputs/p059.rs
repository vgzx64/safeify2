fn main() {
                    .map(|idx| unsafe {
                        // https://www.postgresql.org/docs/13/libpq-exec.html#LIBPQ-PQFNAME
                        // states that the returned ptr is valid till the underlying result is freed
                        // That means we can couple the lifetime to self
                        let ptr = PQfname(self.internal_result.as_ptr(), idx as libc::c_int);
                        if ptr.is_null() {
                            None
                        } else {
                            Some(CStr::from_ptr(ptr).to_str().expect(
                                "Expect postgres field names to be UTF-8, because we \
                     requested UTF-8 encoding on connection setup",
                            ) as *const str)
                        }
}
