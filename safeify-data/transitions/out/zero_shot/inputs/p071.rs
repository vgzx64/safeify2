fn main() {
        let mut stream = unsafe { Pin::new_unchecked(self) }.project().stream;
}
