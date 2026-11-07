    *const str: FromSql<ST, DB>,
    #[allow(unsafe_code)] // ptr dereferencing
        let str_ptr = <*const str as FromSql<ST, DB>>::from_sql(bytes)?;
        // We know that the pointer impl will never return null
        let string = unsafe { &*str_ptr };
        Ok(string.to_owned())
