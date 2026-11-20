fn main() {
        !unsafe { self.inner.get_ref().get_unchecked(self.token) }
}
