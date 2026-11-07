fn main() {
            if self.values.capacity() < id + 1 {
                self.values.reserve(id + 1);
            unsafe { ptr::write(self.values.get_unchecked_mut(id), val) }
            Some(mem::replace(unsafe { self.values.get_unchecked_mut(id) }, val))
}
