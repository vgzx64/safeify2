fn main() {
        unsafe {
            let cap = cmp::min(self.values.capacity(), self.ids.capacity());
            self.values.set_len(cap);
            self.values.shrink_to_fit();
            self.values.set_len(0);
        }
}
