    *const [u8]: FromSql<ST, DB>,
    #[allow(unsafe_code)] // ptr dereferencing
        let slice_ptr = <*const [u8] as FromSql<ST, DB>>::from_sql(bytes)?;
        // We know that the pointer impl will never return null
        let bytes = unsafe { &*slice_ptr };
        Ok(bytes.to_owned())
