# Svelte and Tauri Desktop Build

## Ownership

`webui/src/admin` is the source of the Web/LAN Admin UI. `make web-build`
generates the committed package assets under
`src/codex_rosetta/gateway/admin/dist`; Python packaging never invokes npm.
`webui/src/bootstrap` is a separate privileged local bootstrap UI and is not a
second Admin implementation.

The Tauri process owns only its child sidecar handle and navigation policy. The
Python sidecar owns Gateway initialization and runtime state. Admin HTTP pages
have no Tauri capability. The pipe protocol accepts only `probe`, `init`,
`confirm-local-mode`, `serve`, and `shutdown` messages with the fixed
`ROSETTA_DESKTOP/1` event prefix.

## Toolchain

- Node.js 20.19 or newer, using `webui/package-lock.json`.
- Rust 1.88 or newer, using `src-tauri/Cargo.lock`.
- Python 3.14.6 and PyInstaller 6.21.0 for the native sidecar.
- Native platform build tools. Sidecars are built natively for each target;
  cross-compilation is not assumed.

## Development checks

```bash
make web-check
make web-test
make web-build
conda run -n llm-rosetta pytest -q \
  tests/gateway/test_desktop_protocol.py \
  tests/gateway/test_desktop_sidecar.py
cd src-tauri
cargo fmt --check
cargo clippy --all-targets -- -D warnings
cargo test
```

Build the current native sidecar and a macOS development app with:

```bash
make desktop-sidecar
cd src-tauri
../webui/node_modules/.bin/tauri build --debug --bundles app
```

The desktop bundle must contain the target-triple sidecar under
`Resources/binaries`. Startup validates a versioned ready event, the exact
`127.0.0.1:<port>/admin` URL, and `/health/live` before creating the Admin
window. Startup and shutdown reads are bounded; timeout terminates only the
owned child.

## Release boundary

Desktop release is manual only. Do not add tag-triggered publishing or the
Tauri updater plugin. Build macOS arm64, macOS x86_64, and Windows x86_64 on
their native runners, record SHA-256 values and lockfile identities, then run
install/first-start/login/exit/uninstall smoke tests in clean machines or VMs.

Official macOS artifacts require Developer ID signing and notarization.
Official Windows artifacts require Authenticode. Missing credentials means the
output is a development build and must not be presented as release-ready.
