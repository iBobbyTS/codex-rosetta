# Remediation Wave Scope

- Run: `20260719-1712`
- Baseline: `docs/audit/runs/20260719-1542/`
- Repository base: `HEAD baa57887a4c6ee99b5c9d10995a2959e76f0682a` plus the authorized working-tree remediation wave.
- Authorization: owner authorized remediation of AUD-001, AUD-002, AUD-003 and AUD-005; AUD-004 remains accepted debt.
- Deployment boundary: local process and trusted internal network only. No public-deployment, account-security, availability, backup/restore, HA, RTO/RPO, or artifact-integrity guarantee is claimed.
- Live-call boundary: this audit uses no real Codex/provider/API calls. Development live tests require explicit developer approval; deterministic checks remain local/fake-only.

## In scope

- AUD-002: transactional compaction row/byte/replacement bounds.
- AUD-001: reject Rosetta-version config/state/API migration and deprecated persistence/config aliases; preserve current protocol `api_type` behavior.
- AUD-003: fail-closed approval gate for every repository live-call runner.
- AUD-005: URL-authoritative provider rendering/resolution; exact preset URL matches render the preset option, other URLs render `custom` and remain allowed.
- Tests, profile/coverage/findings ledgers, and targeted re-audit evidence.

## Out of scope

- Real upstream behavior, provider quality, agentabi trajectories, production or LAN deployment smoke, backup/restore, public release hardening, and AUD-004 supply-chain controls.

