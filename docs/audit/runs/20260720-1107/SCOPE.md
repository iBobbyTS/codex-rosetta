# Remediation Re-audit Scope

- Run: `20260720-1107`
- Mode: targeted re-audit after the omission audit `20260719-1802`
- Base: repository commit `baa57887a4c6ee99b5c9d10995a2959e76f0682a` plus the authorized working-tree remediation wave
- In-scope findings: AUD-003, AUD-005, AUD-006, AUD-007, AUD-008, AUD-009, AUD-010 and AUD-011
- Deployment boundary: local process and trusted internal network only; no public deployment or account-security guarantee
- Live-call boundary: no real Codex/provider/API call is permitted in this audit; development live calls require the exact shared approval marker

## In scope

1. Complete enumeration and fail-closed gating of repository live-call entry points.
2. URL-authoritative provider rendering and Admin runtime profile derivation without persisting provider options.
3. Explicit `api_type` validation and propagation of invalid-provider state to referencing model groups.
4. SQLite schema shape validation for columns, constraints, primary keys, and required indexes.
5. Reconciliation of `FINDINGS.md`, `COVERAGE.md`, `SYSTEM-MAP.md`, and the run evidence.

## Excluded

- Real upstream/provider/Codex/agentabi calls, credential reads, browser or LAN deployment, Docker/Compose smoke, backup/restore, long-run disk stress, GitHub settings, and provider-quality claims.
- New product features or compatibility migration layers.

## Acceptance evidence

- Source and tests show each selected failure path is closed or explicitly risk-accepted.
- Deterministic full-suite, lint, and focused contract checks pass.
- Persistent ledgers agree on status, ownership, residual risk, and reopen triggers.
