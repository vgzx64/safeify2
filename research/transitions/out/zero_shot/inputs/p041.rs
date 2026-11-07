fn main() {
        unsafe {
            self.buf.reserve(len);
            let slice = self.buf.get_unchecked_mut(..len);
            self.rdr.read_exact(slice)?;
            Ok(slice)
        }
}
