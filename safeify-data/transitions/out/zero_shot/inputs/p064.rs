  fn to_little_endian(self) -> Self {
    let b = u8::to_le(self.bits());
    unsafe { Self::from_bits_unchecked(b) }
  fn from_little_endian(self) -> Self {
    let b = u8::from_le(self.bits());
    unsafe { Self::from_bits_unchecked(b) }
