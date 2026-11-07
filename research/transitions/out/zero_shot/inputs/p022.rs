fn main() {
            if self.values.capacity() < id + 1 {
                self.values.reserve(id + 1);
            unsafe {
                let space = self.values.get_unchecked_mut(id);
                ptr::write(space, f());
                space
            }
        } else {
            unsafe { self.values.get_unchecked_mut(id) }
}
