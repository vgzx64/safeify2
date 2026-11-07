fn main() {
        self.ids.next().map(|id| unsafe { &*self.values.offset(id as isize) })
}
