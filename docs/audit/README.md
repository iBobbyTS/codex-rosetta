# Versioned Audit Evidence

This directory is the canonical home for persistent audit ledgers, findings,
coverage, system mapping, and run evidence. The approved project profile is
the single file at [`../audit-profile.md`](../audit-profile.md); do not create a
second profile under this directory.

## Current baseline

- Profile: [`../audit-profile.md`](../audit-profile.md)
- System map: [`SYSTEM-MAP.md`](SYSTEM-MAP.md)
- Coverage ledger: [`COVERAGE.md`](COVERAGE.md)
- Findings ledger: [`FINDINGS.md`](FINDINGS.md)
- Latest immutable audit run (historical): [`runs/20260721-2248/REPORT.md`](runs/20260721-2248/REPORT.md)
- Current working-tree status: `AUD-025` and review findings `REV-001`, `REV-002`, and `REV-003` are closed at deterministic evidence depth after independent delta review. Converted Chat, Anthropic, and Google documents and streams retain the target gate and add final source-consumer checking; response diagnostics remain request-local until safe completion plus active-provider/global aggregation, and unsafe terminal exception details are replaced before Trace, RequestLog, Metrics, or memory/SQLite persistence. The independent related cone reports `175 passed`; the final affected cone reports `181 passed`; the full deterministic suite reports `3723 passed, 5 skipped, 11 warnings`; lint, complexity, Codex compatibility, `git diff --check`, and CodeGraph sync pass. No real provider/API/Codex call, deployment, or commit occurred.

Historical run snapshots remain under their original dated directories. In
particular, `runs/20260721-2137/` and `runs/20260721-2248/` are immutable: their
then-current paths and reopen/closure conclusions are not rewritten with the
later terminal-sink repair. They are historical evidence, not current status.
