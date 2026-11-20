fn main() {
        let inner = unsafe { this.inner.get_mut().data.get_unchecked_mut(this.token) };
}
