# Remediation Wave Evidence

## Source and contract evidence

- `GatewayConfig` resolves provider shim behavior from `(api_type, base_url)` exact preset matches. Persisted vendor/variant options are not written by Admin routes; unmatched URLs remain valid custom endpoints.
- Incompatible provider `type`/`shim` fields without `api_type`, legacy `server.api_key`, old persistence files, incompatible SQLite schemas, and removed `request_log.max_entries` are rejected. No migration/backfill path is invoked at startup.
- `PersistenceManager.store_codex_compaction_mapping` performs TTL cleanup, replacement-size validation, per-principal/global row-byte accounting, and the upsert in one `BEGIN IMMEDIATE` transaction.
- Live-call entry points call `require_live_call_approval()` before credentials, run roots, subprocesses, or integration work are started. The exact marker is `CODEX_ROSETTA_ALLOW_LIVE_CALLS=I_UNDERSTAND_REAL_API_CALLS`.

## Deterministic verification

| Check | Result | Scope/limitation |
| --- | --- | --- |
| `conda run -n llm-rosetta pytest -q tests/gateway/test_persistence_sqlite.py tests/observability/test_retention.py` | 92 passed | local SQLite/fake data only |
| targeted config/Admin/profiling/live-gate/provider tests | 122 passed | deterministic/local only |
| `conda run -n llm-rosetta make test` | 3428 passed, 5 skipped, 11 warnings | excludes `tests/integration`; no real API |
| `conda run -n llm-rosetta make lint` | passed | Ruff, format, ty, complexipy |
| `conda run -n llm-rosetta make check-codex-compat` | passed; no blocking changes | 11 semantic rows remain `Possibly unchanged`; source commit `655224ffae098a85efeddf8289171ff3bd2624d1` |
| `git diff --check` + `codegraph sync` | passed | current worktree and index refreshed |

## Negative evidence

- No API key was read for a live run and no external provider/Codex request was sent.
- No deployment, Docker daemon, browser/LAN proxy, GitHub publication, backup/restore, or long-run disk stress claim is made.
