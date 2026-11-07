    fn assert_user_ptr(ptr: usize) {
        if ptr >= USER_END_ADDR {
            unsafe { illegal_instruction() };
