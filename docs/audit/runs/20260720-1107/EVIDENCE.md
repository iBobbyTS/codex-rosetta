# Remediation Re-audit Evidence

## Code and configuration evidence

- Every known real-call Python and shell entry point invokes the shared fail-closed approval gate before reading credentials, creating run roots, constructing clients, or launching subprocesses.
- Provider resolution now requires explicit `api_type`; missing values raise a configuration error. Admin returns `validation_error` for that provider and every referencing model group.
- Provider vendor/variant options are derived at runtime from the authoritative URL and protocol. Admin writes URL/protocol/key data only; exact preset URLs render preset options and unmatched HTTP(S) URLs render the selected protocol's `custom` option.
- Admin default tool profiles use the API's runtime-derived profile and no longer depend on stripped provider metadata.
- SQLite startup validation checks declared column name/type/NOT NULL/primary-key shape and required index names/order for the key persistence tables.
- The profile records the owner decision that arbitrary HTTP(S) custom egress, including configured provider-key delivery, is accepted within the local/LAN boundary. It is not a public SSRF or account-security guarantee.

## Verification

| Check | Result | Scope/limitation |
| --- | --- | --- |
| `conda run -n llm-rosetta make lint` | passed | Ruff, format, ty, and complexity checks |
| `conda run -n llm-rosetta make test` | 3452 passed, 5 skipped, 11 warnings | deterministic suite; integration tests excluded; no real API |
| Live-call gate contract tests | passed within full suite | verifies every enumerated entry point and exact-marker fail-closed behavior |
| Provider/Admin/config focused tests | passed within full suite | fake/local requests only; includes invalid `api_type` propagation and URL rendering |
| SQLite persistence focused tests | passed within full suite | local temporary SQLite databases; no restore or long-run stress claim |
| `git diff --check` | passed | current working tree |

## Negative evidence and residual limits

- No API key was read for a live run and no external provider/Codex request was sent.
- No availability, data-loss recovery, HA/SLO/RTO/RPO, browser, Docker, LAN, public deployment, or upstream-quality conclusion is made.
- Accepted residual risk: arbitrary custom HTTP(S) URLs can receive configured provider keys; this remains an explicit owner decision for the local/LAN boundary.
