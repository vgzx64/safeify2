fn main() {
            virtual_address: addr as u64,
            address: addr as u64,
            size: len as u64,
        unsafe {
            let code_buffer: &[u8] = std::slice::from_raw_parts(addr, len);
            self.write_code_load_record(method_name, clr, code_buffer)
        }
}
