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
- Latest run: [`runs/20260721-2035/REPORT.md`](runs/20260721-2035/REPORT.md)
- Latest status: `AUD-025` is closed at `51f3b2d`. The Responses credential gate now follows Codex active-item and retained-index identities; changing ignored wire IDs is blocked in raw and parsed paths. Focused `296 passed`, phase-separated adversarial selection `8 passed`, full deterministic suite `3676 passed, 5 skipped`, and lint/compatibility checks passed. No real provider/API/Codex call or deployment occurred.

Historical run snapshots remain under their original dated directories. They
are preserved as historical evidence and may contain paths or conclusions that
were true before this current baseline; they are not current status.
