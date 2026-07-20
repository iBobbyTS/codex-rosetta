# Omission-Remediation Re-audit Evidence

## Code evidence

| Finding | Commit | Evidence |
| --- | --- | --- |
| AUD-012 | `477fa00` | Shared `AsyncClient` uses `max_redirects=0`; an independent two-server loopback test proves the redirect target receives no request. |
| AUD-006 | `35521ab` | All 24 `examples/rest_based/*.py` and `examples/sdk_based/*.py` entry points call the shared approval gate before `load_dotenv()`; the contract test discovers both directories dynamically. |
| AUD-010 | `ec8419b` | SQLite `PRAGMA index_list` attributes `unique`, `origin`, and `partial` are compared with the expected schema in addition to index columns; unique and partial mismatch tests fail closed. |
| AUD-009 | `804efef` | Exact preset URLs use canonical `responses`, `chat`, `anthropic`, `google` order; unmatched URLs default to Responses; each active missing value warns once per config construction; only the runtime copy/Admin response receives the inferred value. |
| AUD-008/011 | this ledger commit | Profile and ledgers retain accepted direct custom HTTP(S) egress within local/LAN scope, prohibit redirect expansion, and supersede the old missing-`api_type` invalidity conclusion. |

## Verification

| Check | Result | Scope/limitation |
| --- | --- | --- |
| Redirect-focused transport test | 3 passed | Local loopback only; no provider credentials or external network. |
| Live-call configuration contract | 51 passed | Static/source contract plus local gate execution; no real call. |
| SQLite schema-focused tests | 4 passed | Temporary local SQLite databases. |
| Config and Admin route suites | 189 passed | Local/fake route behavior; no upstream request. |
| `conda run -n llm-rosetta make lint` | passed | Ruff, format, ty, complexity ratchet; 349 files formatted. |
| `conda run -n llm-rosetta make test` | 3480 passed, 5 skipped, 11 warnings | `tests/integration` excluded by Makefile; no real API call. |
| `git diff --check` | passed before ledger edits | Code baseline clean; repeated after ledger creation. |

## Negative evidence and residual limits

- No real API key was used and no external provider/Codex request was sent.
- Direct requests to an operator-configured arbitrary HTTP(S) custom URL or proxy can still receive the provider credential; this remains owner-accepted only for local/LAN deployments.
- No availability, data-loss recovery, HA/SLO/RTO/RPO, public deployment, provider quality, DNS rebinding, or proxy-behavior conclusion is made.
- AUD-013 was not opened: missing/disabled provider model groups retain the existing silent-skip behavior by explicit owner decision.
