# Token redaction and diagnostic retention semantic correction
Date: 2026-07-09
Codex version: 0.144.0

Historical supporting evidence; use the maintained compatibility ledger and
reports for current conclusions.

## Confirmed contract

- Preserve error request bodies, converted bodies, response text, and ordinary fields.
- Redact only Gateway/provider API tokens, Bearer/Authorization tokens, explicit token/api_key fields, and exact configured API-token values.
- Preserve ordinary password, secret, client_secret, and proxy-password values unless the value is also a configured API token.
- Preserve the pre-existing 10,000-record error-dump cap. Do not add age or total-byte deletion.
- Keep orphan body cleanup after count pruning.
- Release policy is GitHub UI manual Release only; do not require Docker publication exercises.

## Root cause

The first remediation treated a generic secret-hardening recommendation as authoritative after the user had already narrowed the business semantics. The redaction key set, config value collection, and retention pruning therefore exceeded the approved scope.

## Verified correction

- Token-field detection and configured-token collection no longer include Admin passwords, ordinary passwords, secret/client-secret fields, or proxy passwords.
- Runtime setup and hot reload pass only configured Gateway/provider API tokens plus the internal Admin API token to persistence and stream traces.
- Error-dump pruning uses only `DEFAULT_DUMP_MAX = 10000` and orphan body cleanup.
- English/Chinese gateway security docs and the first-round `FULL.md`/`REPORT.md` state the approved behavior.
- Focused tests: 58 passed.
- `make lint`: Ruff, format, and ty passed.
- `make test`: 2,378 passed, 4 skipped, 28 warnings.
- `make check-codex-compat`: passed, Changed: None.
- Python 3.10.20 and 3.14.6 wheel import/Admin-resource/CLI-version smoke: passed.
- Diff checks passed; `_vendor/**` remained unchanged.
