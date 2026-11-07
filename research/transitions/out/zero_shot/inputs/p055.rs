fn main() {
        let result_status = unsafe { PQresultStatus(internal_result.as_ptr()) };
        match result_status {
                let column_count = unsafe { PQnfields(internal_result.as_ptr()) };
                let row_count = unsafe { PQntuples(internal_result.as_ptr()) };
}
