# S02 Handoff — Sub2API projection and New API pricing seam

## Result

- Extended `/admin/api/config/providers/<name>/sub2api-keys` projections with
  the UI-compatible `current_concurrency: null` field while retaining only the
  approved editor fields.
- Added `POST /admin/api/config/providers/<name>/new-api-pricing`. The route
  accepts `base_url` and optional `bearer_key` (also accepts the existing
  `api_key` spelling), performs a generic transport `GET` to
  `{base_url}/api/pricing`, and returns ordered `group_ratio` values.
- Malformed payloads, transport failures, and non-2xx upstream responses return
  bounded, readable 502 errors; no account ID or stored Sub2API credential is
  required.

## Files

- `src/codex_rosetta/gateway/admin/routes/accounts.py`
- `src/codex_rosetta/gateway/admin/routes/__init__.py`
- `tests/gateway/test_admin_accounts.py`

## Validation

- `ruff format` (changed files): passed
- `ruff check` (changed files): passed
- `pytest -q tests/gateway/test_admin_accounts.py`: **58 passed**

## Commit

Commit: included in the coherent S02 commit; parent should record the final
`git rev-parse HEAD` after integration.
