#!/bin/sh
# measure.sh: build gt-core and the example plan for a bare-metal target and
# print the size of the linked image by section.
#
#   embedded/measure.sh [target] [gt-core features]
#
# target defaults to thumbv7em-none-eabihf (Cortex-M4F/M7F). It must be
# installed: rustup target add <target>. The image is embedded/example-bare's
# `firmware` binary: a reset entry that calls the conversion once. It is
# linked with the linker Rust ships (rust-lld), unused sections dropped.
# Build output goes to embedded/target and is removed with `cargo clean`.
set -eu
here=$(cd "$(dirname "$0")" && pwd)
target=${1:-thumbv7em-none-eabihf}
features=${2:-}
export CARGO_TARGET_DIR="$here/target"
cd "$here"
RUSTFLAGS="-C linker=rust-lld -C link-arg=--entry=_start -C link-arg=--gc-sections -C link-arg=-Map=$CARGO_TARGET_DIR/firmware.map" \
  cargo build -q -p example-bare --bin firmware --features "firmware $features" --release --target "$target"
python3 -I "$here/elfsize.py" "$CARGO_TARGET_DIR/$target/release/firmware" --stack gt_rid_location_to_cat062 --depth "${GT_DEPTH:-12}"
