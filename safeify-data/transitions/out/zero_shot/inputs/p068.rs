fn main() {
            // Efficient copy_nonoverlapping (memcpy)
                                    // &mut and & can never overlap
                                    unsafe {{
                                        copy_nonoverlapping(vals[..].as_ptr(),
                                                            _self.packet[current_offset..].as_mut_ptr(),
                                                            vals.len())
                                    }}
}
