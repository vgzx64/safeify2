fn main() {
                    self.reserve(1);
                    let start = self.as_mut_ptr();
                    ptr = start.add(index);
                    cur = ptr.add(num_added);
                    ptr::copy(cur, cur.add(1), old_len - index);

                    guard.start = start;
                    guard.len += 1;
                    guard.skip.end += 1;
}
