fn main() {
                let mut pos = 0;
                let mut result: Self;
                unsafe {
                    result = std::mem::uninitialized();
                    for i in 0 .. ($x) {
                        std::ptr::write(&mut result[i], <T>::read_bytes_default_be(&bytes[pos .. pos + len]));
                        pos += len;
                    }
                }
                result
}
