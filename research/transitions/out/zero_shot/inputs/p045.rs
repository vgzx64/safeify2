fn main() {
        unsafe {
            SmallVec {
                capacity: 0,
                data: SmallVecData::from_inline(mem::uninitialized()),
            }
}
