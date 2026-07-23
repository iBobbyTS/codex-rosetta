#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
TARGET_TRIPLE="${TARGET_TRIPLE:-$(rustc -vV | sed -n 's/^host: //p')}"
SOURCE_NAME="codex-rosetta-desktop-sidecar"
DEST_NAME="${SOURCE_NAME}-${TARGET_TRIPLE}"

case "$TARGET_TRIPLE" in
  *-windows-*)
    SOURCE_NAME="${SOURCE_NAME}.exe"
    DEST_NAME="${DEST_NAME}.exe"
    ;;
esac

cd "$ROOT/packaging/pyinstaller"
pyinstaller --noconfirm --clean codex-rosetta-desktop.spec
install -m 0755 "dist/${SOURCE_NAME}" "$ROOT/src-tauri/binaries/${DEST_NAME}"
shasum -a 256 "$ROOT/src-tauri/binaries/${DEST_NAME}"
