#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
TARGET_TRIPLE="${TARGET_TRIPLE:-$(rustc -vV | sed -n 's/^host: //p')}"
HOST_TRIPLE="$(rustc -vV | sed -n 's/^host: //p')"
BUILD_ID="${BUILD_ID:-$(date -u +%Y%m%d-%H%M%S)}"
OUTPUT_DIR="$ROOT/dist/desktop/$TARGET_TRIPLE/$BUILD_ID"

if [[ "$TARGET_TRIPLE" != "$HOST_TRIPLE" ]]; then
  echo "Desktop bundles must be built natively (host=$HOST_TRIPLE target=$TARGET_TRIPLE)." >&2
  exit 2
fi

cd "$ROOT/webui"
npm ci
npm run check
npm run test
npm run build

cd "$ROOT"
TARGET_TRIPLE="$TARGET_TRIPLE" ./scripts/build_desktop_sidecar.sh
cargo fmt --manifest-path src-tauri/Cargo.toml --check
cargo clippy --manifest-path src-tauri/Cargo.toml --all-targets --all-features -- -D warnings
cargo test --manifest-path src-tauri/Cargo.toml
npm --prefix webui exec tauri build -- --config src-tauri/tauri.conf.json

mkdir -p "$OUTPUT_DIR"
find "$ROOT/src-tauri/target/release/bundle" -maxdepth 5 -type f -exec cp {} "$OUTPUT_DIR/" \;
(
  cd "$OUTPUT_DIR"
  find . -maxdepth 1 -type f ! -name SHA256SUMS -exec shasum -a 256 {} + > SHA256SUMS
)
shasum -a 256 "$ROOT/pyproject.toml" "$ROOT/webui/package-lock.json" "$ROOT/src-tauri/Cargo.lock" > "$OUTPUT_DIR/BUILD-INPUTS.sha256"
echo "Unsigned native development artifacts: $OUTPUT_DIR"
