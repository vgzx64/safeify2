#!/bin/sh
# Wrapper for building/running the engine in this environment.
#
# The default CARGO_HOME (/home/user/.cargo) is read-only here, so point cargo
# at a writable cache inside the workspace and keep build artifacts out of the
# repository tree. Everything lives under .tools/, which is gitignored.
set -e
ROOT=$(cd "$(dirname "$0")/.." && pwd)
export CARGO_HOME="$ROOT/.tools/cargo-home"
export CARGO_TARGET_DIR="$ROOT/.tools/cargo-target/engine"
export CARGO_NET_RETRY=5
export CARGO_HTTP_TIMEOUT=60
mkdir -p "$CARGO_HOME" "$CARGO_TARGET_DIR"
cd "$ROOT/safeify-lint"

# The vendored rust-analyzer carries one local fix: `no_deps` must apply to the
# analysed package, not to the sysroot (otherwise std loses its alloc/core edges
# and most of std becomes invisible). Apply the patch when it is not applied.
PATCH="$ROOT/safeify-lint/patches/rust-analyzer-sysroot-deps.patch"
if [ -f "$PATCH" ] && git -C "$ROOT/vendors/rust-analyzer" apply --check "$PATCH" 2>/dev/null; then
  git -C "$ROOT/vendors/rust-analyzer" apply "$PATCH"
  echo "cargo.sh: applied $(basename "$PATCH")" >&2
fi
exec cargo "$@"
