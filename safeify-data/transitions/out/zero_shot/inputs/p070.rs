fn main() {
            // Safety: Last receiver, drop the value
            self.slot.val.with_mut(|ptr| unsafe { *ptr = None });
}
