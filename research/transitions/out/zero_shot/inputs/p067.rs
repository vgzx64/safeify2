  fn to_little_endian(self) -> Self {
    let b = u64::to_le(self.bits());
    unsafe { Self::from_bits_unchecked(b) }
  fn from_little_endian(self) -> Self {
    let b = u64::from_le(self.bits());
    unsafe { Self::from_bits_unchecked(b) }
