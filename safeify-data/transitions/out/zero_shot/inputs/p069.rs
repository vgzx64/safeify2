fn main() {
        self.slot.val.with(|ptr| unsafe { (*ptr).clone() })
}
