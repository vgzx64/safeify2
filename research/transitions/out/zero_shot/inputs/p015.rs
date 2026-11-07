fn main() {
		// SAFETY: creating a reference 1 byte past the last valid byte is safe as long as we don't dereference it
		let data_ptr_end: *const u8 = unsafe { data.get_unchecked(data.len()) };
		if data_ptr_end < data.as_ptr() || {
			// Verify that max_data_ptr can never overflow and that data_ptr.add(N) can't overflow
			if let Some(index) = data.len().checked_add(IcedConstants::MAX_INSTRUCTION_LENGTH + 4) {
				data.as_ptr().wrapping_add(index) < data.as_ptr()
}
