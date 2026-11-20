#!/bin/sh
# One-time setup: give rust-analyzer access to std sources without rustup.
#
# The system toolchain (/opt/rust-bin-1.97.1, root-owned) lacks the rust-src
# component, which rust-analyzer needs to load the standard library ("can't
# load standard library, try installing rust-src"). We cannot write to /opt,
# so we:
#   1. download rust-src for the exact local rustc version,
#   2. build a symlink-farm sysroot under ~/.local/share/ra-detect/sysroot,
#   3. install a `rustc` shim (PATH-prepended only for the rust-analyzer
#      child process, see ra_client.ra_env) that redirects `--print sysroot`
#      to that farm.
set -eu

RUSTC=/usr/bin/rustc
VER=$($RUSTC --version | awk '{print $2}')
D=$HOME/.local/share/ra-detect
TARBALL=/tmp/rust-src-$VER.tar.xz

echo "toolchain version: $VER"
[ -f "$TARBALL" ] || curl -fsSL -o "$TARBALL" "https://static.rust-lang.org/dist/rust-src-$VER.tar.xz"
mkdir -p "$D/tmp" "$D/sysroot/lib/rustlib" "$D/shim"
tar xf "$TARBALL" -C "$D/tmp"
ln -sfn "$D/tmp/rust-src-$VER/rust-src/lib/rustlib/src" "$D/sysroot/lib/rustlib/src"
SYSROOT=$($RUSTC --print sysroot)
for e in "$SYSROOT"/lib/rustlib/*; do
    n=$(basename "$e")
    [ "$n" = src ] || ln -sfn "$e" "$D/sysroot/lib/rustlib/$n"
done
ln -sfn "$SYSROOT/libexec" "$D/sysroot/libexec"
ln -sfn "$SYSROOT/bin" "$D/sysroot/bin"
cat > "$D/shim/rustc" <<EOF
#!/bin/sh
if [ "\$1" = "--print" ] && [ "\$2" = "sysroot" ]; then
  echo "$D/sysroot"
  exit 0
fi
exec $RUSTC "\$@"
EOF
chmod +x "$D/shim/rustc"
PATH="$D/shim:$PATH" rustc --print sysroot
echo "shim OK; rust-analyzer will pick it up automatically via ra_env()"
