fn main() {
        "We've written the aggregator to the aggregate context, but it could not be retrieved.";
    let n_bytes: i32 = core::mem::size_of::<OptionalAggregator<A>>()
        .try_into()
        .expect("Aggregate context should be larger than 2^32");
    let aggregate_context = unsafe {
        // This block of unsafe code makes the following assumptions:
        //
        // * sqlite3_aggregate_context allocates sizeof::<OptionalAggregator<A>>
        //   bytes of zeroed memory as documented here:
}
