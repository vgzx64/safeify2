fn main() {
            #[allow(unsafe_code)] // pointer cast
                let bytes = unsafe {
                    let bytes_ptr = self as *const MysqlTime as *const u8;
                    slice::from_raw_parts(bytes_ptr, mem::size_of::<MysqlTime>())
                };
                out.write_all(bytes)?;
}
