# Omission-Remediation Re-audit Scope

- Run: `20260720-1239`
- Mode: targeted repair and re-audit after the second omission pass
- Code baseline: `804efef03d91f72771f27228bde26003d6ba40fa`
- In-scope findings: AUD-006, AUD-008, AUD-009, AUD-010, AUD-011, AUD-012; candidate AUD-013 disposition
- Deployment boundary: local process and trusted internal network only; no public deployment or account-security guarantee
- Live-call boundary: no real Codex/provider/API call is permitted in this audit

## In scope

1. Reject every upstream redirect before a credential-bearing follow-up request.
2. Gate every executable REST/SDK example before dotenv, credentials, clients, or network work.
3. Validate SQLite required-index columns, uniqueness, origin, and partial flag.
4. Infer missing `api_type` from exact preset URL support order, default custom URLs to Responses, emit a warning, render the inferred value, and avoid config write-back.
5. Reconcile the approved profile and all persistent ledgers to the exact code baseline.

## Excluded

- Real upstream/provider/Codex/agentabi calls, credential reads for live execution, browser/LAN deployment, Docker/Compose smoke, backup/restore, long-run disk stress, DNS/proxy adversarial tests, GitHub settings, and provider-quality claims.
- AUD-013 implementation: the owner rejected added missing/disabled-provider group validation as disproportionate to the current Gateway scale.

## Acceptance evidence

- Focused tests prove each repaired failure path and negative side effect.
- `make lint` and the full deterministic non-integration suite pass.
- Profile, findings, coverage, system map, README, and this run agree on decisions, residual risks, and exact commit identities.
