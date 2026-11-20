fn main() {
    unsafe {
        // The `enter_wasm` call below will reset the store context's
        // `stack_chain` to a new `InitialStack`, pointing to the
        // stack-allocated `initial_stack_csi`.
        let mut initial_stack_csi = VMCommonStackInformation::running_default();
}
