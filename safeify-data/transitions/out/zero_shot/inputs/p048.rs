fn main() {
        return;
    }
    let delta = min_len - len;
    vec.reserve(delta);
    unsafe {
        let mut ptr = vec.as_mut_ptr().offset(len as isize);
        // Write all elements except the last one
        for i in 1..delta {
            ptr::write(ptr, value.clone());
            ptr = ptr.offset(1);
            // Increment the length in every step in case clone() panics
            vec.set_len(len + i);
        }

        // We can write the last element directly without cloning needlessly
        ptr::write(ptr, value);
        vec.set_len(len + delta);
    }
}

    unsafe {
        // Resize. In future versions of Rust, we should
        // be able to use `vec.resize`.
        vec.set_len(size);
        for i in 0 .. size {
            vec[i] = value.clone();
        }
    }
}
