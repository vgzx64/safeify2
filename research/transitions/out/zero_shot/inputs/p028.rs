        // values.capacity() should an upper bound on ids.
            assert!(id < self.values.capacity())
    /// Clear the values vec. Unsafe since ids is not updated.
    unsafe fn drop_values(&mut self) {
            ptr::drop_in_place(self.values.get_unchecked_mut(id))
    /// Find the next empty space after has been filled.
