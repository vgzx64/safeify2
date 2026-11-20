#!/bin/sh
# Resolution smoke survey: loads each crate and prints how much of it the
# semantic engine can see. Usage: ./smoke.sh <crate-dir>...
BIN=$(cd "$(dirname "$0")/../../.." && pwd)/.tools/cargo-target/engine/release/safeify-lint
for c in "$@"; do
  "$BIN" --crate "$c" 2>/dev/null | python3 -c 'import json,sys
d = json.load(sys.stdin)
print("%-34s fns %4d/%-4d calls %4d/%-4d methods %4d/%-4d %5dms" % (
    d["crate"].split("/")[-1], d["fns_resolved"], d["fns"],
    d["calls_resolved"], d["calls"], d["method_calls_resolved"],
    d["method_calls"], d["load_ms"]))'
done
