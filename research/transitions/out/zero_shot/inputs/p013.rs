fn main() {
    let wrapped = fill(unsafe { str::from_utf8_unchecked(input) }, max_width);
}
