#!/bin/sh
# Wrapper for building/running the engine in this environment.
#
# The default CARGO_HOME (/home/user/.cargo) is read-only here, so point cargo
# at a writable cache inside the workspace and keep build artifacts out of the
# repository tree. Everything lives under .tools/, which is gitignored.
set -e
ROOT=$(cd "$(dirname "$0")/../../.." && pwd)
export CARGO_HOME="$ROOT/.tools/cargo-home"
export CARGO_TARGET_DIR="$ROOT/.tools/cargo-target/engine"
export CARGO_NET_RETRY=5
export CARGO_HTTP_TIMEOUT=60
mkdir -p "$CARGO_HOME" "$CARGO_TARGET_DIR"
exec cargo "$@"
