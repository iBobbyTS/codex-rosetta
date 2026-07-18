# Model-group restart notice after an apparently routing-only edit
Date: 2026-07-15
Codex version: 0.144.0

Historical compatibility evidence; use the maintained ledger and reports for
current conclusions.

## Confirmed observations

- The user restarted the gateway and refreshed the Admin page, then editing a model group still showed the persistent Codex restart notice.
- The notice can only be shown when a successful Admin mutation response contains `X-Codex-Restart-Required: true`.
- That header is emitted only when `CodexLocalModeTransaction.changed` is true after applying the local-mode transaction.
- Current automated coverage proves that a synthetic Provider-only edit with byte-identical model input does not rewrite either managed Codex file.
- The live gateway process imports this checkout, so stale installed code is not the cause.
- With the live gateway config, the generated catalog is byte-identical while the generated `config.toml` is one byte longer on every sync.
- The byte difference is one additional blank line after the managed `[memories]` assignments. `_edit_memory_model_settings` adds a separator but preserves the separator already present before the next TOML table.

## Root cause

1. Confirmed: memory-setting serialization is not idempotent when another TOML table follows `[memories]`, so every model-group save rewrites `config.toml`.

## Resolution

- `_edit_memory_model_settings` now adds a separator only when no retained blank
  line already separates `[memories]` from the next table.
- Transaction and Admin-route regression tests now use configured memory model
  overrides and prove a second sync performs no writes and emits no restart header.
- Against the live gateway config and Codex Home, both generated targets are now
  byte-identical to the files on disk.

## Commands already run

- `git status --short`
- `codegraph explore` over `put_model_group`, `build_model_catalog`, and `CodexLocalModeTransaction.apply`
- Relevant local-mode/Admin tests from the first pass; synthetic Provider-only coverage passed.
- Live process/import inspection and byte-level target comparisons for both managed Codex files.
- `pytest -q tests/gateway/test_local_mode.py tests/gateway/test_admin_config_routes.py tests/gateway/test_admin_json_routes.py` (`162 passed`).
- `make lint` (passed; restored Complexipy's unrelated nondeterministic snapshot rewrite).
