fn main() {
    // SAFETY: Only ASCII characters are valid in identifiers
    unsafe {
        let ident = input.get_unchecked(..len);
        *input = input.get_unchecked(len..);
        Ok(ident)
    }
}
