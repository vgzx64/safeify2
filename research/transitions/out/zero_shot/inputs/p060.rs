    StatementPosition = 'P' as i32,
}

fn get_result_field<'a>(res: *mut PGresult, field: ResultField) -> Option<&'a str> {
    let ptr = unsafe { PQresultErrorField(res, field as libc::c_int) };
    if ptr.is_null() {
        return None;
    }

    let c_str = unsafe { CStr::from_ptr(ptr) };
    c_str.to_str().ok()
}
