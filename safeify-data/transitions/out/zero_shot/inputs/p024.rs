fn main() {
            unsafe {
                if pred(id, values.get_unchecked(id)) {
                    true
                } else {
                    *space = cmp::min(*space, id);
                    ptr::drop_in_place(values.get_unchecked_mut(id));
                    false
                }
}
