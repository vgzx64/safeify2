fn main() {
        let mut values = Vec::from_iter(iter);
        unsafe { values.set_len(0) }
        let space = values.capacity();
        let ids = IdSet::new_filled(values.capacity());
        IdMap {
            values,
}
