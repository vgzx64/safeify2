fn main() {

            // Operating system can fail to make memory accessible.
            let old_byte_size = self.byte_size();
            make_accessible(
                unsafe { self.base.as_mut_ptr().add(old_byte_size) },
                new_byte_size - old_byte_size,
            )?;
        }
}
