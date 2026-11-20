fn main() {
        let mut key_buffer = Vec::with_capacity(key_length);
        let mut value_buffer = Vec::with_capacity(value_length);
        unsafe {
            key_buffer.set_len(key_length);
            value_buffer.set_len(value_length);
        }
}
