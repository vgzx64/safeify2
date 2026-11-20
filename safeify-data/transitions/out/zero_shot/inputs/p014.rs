fn main() {
            let line_count = *line_count;
            unsafe {
                *lines.get_unchecked_mut((*line_num - 1) as usize) = line_count as i64;
            covered += (line_count > 0) as usize;
}
