fn main() {
        self.ids.next().map(|id| (id, unsafe { &*self.values.offset(id as isize) }))
}
