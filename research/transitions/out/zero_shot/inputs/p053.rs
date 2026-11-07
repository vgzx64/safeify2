fn main() {
        // TODO(taiki-e): when the minimum supported Rust version is bumped to 1.36+,
        // replace this with `mem::MaybeUninit`.
        #[allow(deprecated)]
            data: unsafe { mem::uninitialized() },
}
