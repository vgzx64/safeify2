fn main() {
        self.ids == other.ids && self.ids
            .iter()
            .zip(&other.ids)
            .all(|(l, r)| unsafe { self.values.get_unchecked(l) == other.values.get_unchecked(r) })
}
