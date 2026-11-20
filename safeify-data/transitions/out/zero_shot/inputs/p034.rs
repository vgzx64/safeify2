fn main() {
        self.ids.next().map(|id| unsafe { &mut *self.values.offset(id as isize) })
}
