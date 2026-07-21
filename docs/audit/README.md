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
- Latest run: [`runs/20260720-1859/REPORT.md`](runs/20260720-1859/REPORT.md)
- Latest status: AUD-017 and AUD-018 are `Closed` after authorized deterministic remediation. Credential collisions now fail closed without rewriting successful SSE/JSON, raw SSE is released only at complete safe event boundaries, and Admin model discovery rejects invalid provider JSON schemas with a stable non-sensitive error. No real provider/API call occurred in this run.

Historical run snapshots remain under their original dated directories. They
are preserved as historical evidence and may contain paths or conclusions that
were true before this current baseline; they are not current status.
