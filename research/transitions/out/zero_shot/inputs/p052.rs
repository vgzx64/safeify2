fn main() {
            let mut result = vec![T::deserialize_reader(reader)?];

            let p = result.as_mut_ptr();
            unsafe {
                forget(result);
                let len = len.try_into().map_err(|_| ErrorKind::InvalidInput)?;
                let result = Vec::from_raw_parts(p, len, len);
                Ok(result)
            }
}
