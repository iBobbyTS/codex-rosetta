# Web Admin and Desktop App

Codex-Rosetta uses the same Svelte 5 Admin application in a browser and in the
Tauri 2 desktop shell. Python remains the only owner of authentication,
configuration, Provider credentials, model routing, and upstream requests.

## Web and LAN use

Start the Gateway normally and open `/admin`. Deep links such as
`/admin/providers` and `/admin/logs` can be refreshed directly. LAN deployment
uses the configured Gateway bind address and the existing Admin password and
Gateway API-key controls.

The supported deployment boundary remains local-machine and trusted-LAN use.
There is no public-Internet account-security, availability, or data-recovery
commitment. The product has one Admin and may have multiple Gateway API keys;
it is not a multi-user system.

## Desktop first start

The desktop app manages only the loopback Gateway sidecar that it starts. On
first start it asks for a non-empty Admin password and then asks separately
whether Codex local mode should be enabled. Enabling local mode updates Codex
configuration and the model catalog on that computer. Declining leaves Codex
Home unchanged.

After the sidecar binds `127.0.0.1` and passes `/health/live`, the app opens the
same `/admin` UI used by the web deployment. The Admin window has no Tauri IPC
capability. The desktop app cannot connect to an existing or remote Gateway and
does not expose its managed Gateway to the LAN.

## Troubleshooting

- A port-conflict error means the configured stable desktop port is already in
  use. The app fails closed and never opens the unknown service on that port.
- A configuration error must be fixed in the desktop-owned configuration
  directory; the app does not silently replace an existing file.
- Closing the app requests a graceful shutdown of its own sidecar. It does not
  scan for or terminate processes by name, PID file, or port.
- Desktop releases are manual. There is no automatic updater or background
  startup service.

Current repository validation covers a macOS arm64 development bundle. A build
without platform signing and notarization is a development build, not an
official release.
