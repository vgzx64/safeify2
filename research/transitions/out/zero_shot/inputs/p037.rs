fn main() {
        self.ids.next().map(|id| (id, unsafe { ptr::read(self.values.get_unchecked(id)) }))
}
}
