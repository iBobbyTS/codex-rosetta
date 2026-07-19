# Full Audit Ledger

Audit opened: 2026-07-10 14:06 MDT  
Audit closed: 2026-07-10 14:17 MDT  
Profile: `.agent-work/audit/PROFILE.md` (Draft)  
Scope: Independent round 14 review of the current uncommitted repository state, prioritizing Codex compatibility, gateway trust/state boundaries, persistence, conversion correctness, release integrity, and test quality.

| Area | Status | Severity | Files | Notes |
| --- | --- | --- | --- | --- |
| Repository reality and change surface | Reviewed | No Action | working tree, diff, prior ledger | 97 tracked modified files plus 30 untracked files; no staged diff; user work preserved |
| Gateway state and persistence | Reviewed | No Action | `gateway/proxy.py`, `observability/persistence.py`, lifecycle routes/tests | Principal-fair quotas, exact encrypted replay, transaction/accounting, TTL, failure handling, and lifecycle sampled; no new defect |
| Converter and remote image handling | Reviewed | No Action | Google/OpenAI Responses converter paths, image worker/fetch policy, tests | Proxy ownership, SSRF/DNS pinning, redirect/MIME/size/deadline/cancellation boundaries and Responses shape changes sampled |
| Auth, Admin, config, and diagnostics | Reviewed | No Action | auth/CORS/admin/config/observability | Fail-closed `/v1`, Admin token/CORS, config CAS/activation, secret redaction and public-health contract sampled |
| Release, Docker, CI, and vendoring | Reviewed | Track as Debt | package metadata, Makefile, Docker, CI, vendored diff | Local version/static compatibility gates pass; manual provenance, external CI/live evidence, and Draft-profile controls remain known debt |
| Independent verification | Reviewed | No Action | full lint/test plus compatibility/release/diff checks | 2717 passed, 4 skipped; lint/type, static compatibility, release version, and diff checks pass |

## Audit framing

- Highest-priority attributes: protocol correctness, reliability, credential/data security, resource isolation, persistence consistency, release integrity, and maintainability.
- Draft-profile gaps remain owner decisions: legal/privacy baseline, ASVS target, SLO/error budget, incident response, artifact signing/SBOM, dependency policy, and CI permissions.
- The broad dirty worktree belongs to the user and is preserved. This audit writes only ignored audit artifacts.

## Repository reality and sampling basis

- Branch: `master`, one commit ahead of `origin/master`; HEAD remains `eb94742` (`feat(admin): add read-only tool catalog`).
- Working tree: 97 tracked modified files and 30 non-ignored untracked files; tracked diff is 9,018 insertions and 1,597 deletions. No staged changes were observed.
- High-churn and high-risk samples: `gateway/proxy.py`, `gateway/app.py`, `gateway/auth.py`, `gateway/config.py`, Admin config/auth/key routes, HTTP transport, Google URL-image conversion, `observability/persistence.py`, tool-mapping crypto, CI/Makefile/package/release metadata, and their behavioral tests.
- Earlier audit ledgers were used only to avoid repackaging accepted debt and to identify repaired boundaries requiring independent resampling. Current source and executable checks are the evidence for this round.

## Gateway state and persistence

- Reviewed `ProviderMetadataStore` and `WindowToolSearchStore` accounting across principal/scope ownership, replacement, same-principal eviction, TTL, clear, combined loaded/deferred references, canonical JSON bytes, nested tool counts, and lock-protected mutation.
- Reviewed encrypted tool-mapping row/session/principal/global limits, replacement-aware deltas, `BEGIN IMMEDIATE`, rollback, accounting validation before replay, encrypted-v1 backfill, key/AAD binding, expiry cleanup, and bounded session query.
- Traced application lifecycle ownership for request-local vs persistent scopes and non-streaming/streaming completion cleanup. The fail-closed behavior when exact mapping persistence or replay is unavailable remains internally consistent with the documented contract.
- No new Must Fix, Should Plan, or distinct Track-as-Debt issue was found. Existing production-scale capacity benchmarking and live compact/resume/restart verification remain required but are already recorded.

## Converter, stream, and remote-image handling

- Reviewed Google URL-image conversion policy propagation from app-owned provider proxy through `ConversionPipeline` and Google message/content conversion.
- Sampled public-address validation, mixed public/private DNS rejection, direct numeric connection pinning, redirect revalidation, explicit-proxy ownership, disabled environment proxies, MIME/size limits, one deadline, cancellation, and fixed daemon worker capacity/lifecycle.
- Reviewed current OpenAI Responses namespace aggregation, passthrough event typing, stream-context state cloning, and tool API return typing changes against their tests.
- Sampled primary and auxiliary HTTP response envelopes, SSE line/event limits, identity encoding, connection cleanup, and the already accepted absence of a total successful SSE duration/size budget.
- No new actionable converter, stream, SSRF, or worker-lifecycle finding was confirmed.

## Auth, Admin, config, and diagnostics

- Traced fail-closed authentication for the complete `/v1` namespace, principal assignment, internal/Admin token separation, Admin API authorization, strict live Admin CORS origins, and public preflight behavior.
- Sampled config load/write digest CAS, owner-only atomic replacement, backup/activation rollback, app-owned hot reload, API-key mutation guards, and prepared activation of auth/redaction/CORS/persistence state.
- Reviewed token/API-key/Bearer redaction for request logs, metrics, health, stream trace, error dumps, and operational mapping comparison/replay boundaries.
- Existing accepted semantics were not reopened: one privileged Admin role, inline Admin SPA/CSP limitation, public-health non-token diagnostic content, and token-only rather than arbitrary-secret redaction.
- No new actionable finding was confirmed.

## Release, CI, Docker, and agent/runtime knowledge

- `make check-release-version RELEASE_TAG=v0.144.0.r0` passes for source version `0.144.0.r0`.
- `make check-codex-compat` passes against source commit `2e8c3756f95789c215d9ea9a5ade6ec377934b3f`; Changed: None, with 12 groups explicitly remaining `Possibly unchanged`.
- CI covers Python 3.10 and 3.13 lint/test and clean-wheel core/gateway smoke. Make/Docker use the current checkout wheel; publishing targets remain disabled/manual.
- The modified `_vendor/**` paths remain contrary to ordinary direct-edit policy but were previously compared to the local upstream vendoring source; this round did not modify or re-vendor them and found no new mismatch evidence.
- Known debt remains: external GitHub Actions evidence, real release provenance/signing/SBOM, dependency vulnerability/license review, and approved owner/control baselines.

## Independent verification

- `conda run -n llm-rosetta make lint`: passed; Ruff check, Ruff format check (290 files), and `ty check` passed.
- `conda run -n llm-rosetta make test`: passed; **2717 passed, 4 skipped, 9 warnings** in 17.73 seconds.
- `conda run -n llm-rosetta make check-codex-compat`: passed; source commit and static contract above.
- `conda run -n llm-rosetta make check-release-version RELEASE_TAG=v0.144.0.r0`: passed.
- `git diff --check`: passed.
- Not run this round: integration tests requiring credentials, agentabi/live Codex/provider matrix, browser Admin, Docker/Compose build, Python 3.10/3.13 clean-wheel smoke, external GitHub Actions, load/cost/capacity benchmarks, vulnerability/license scans, backup/restore drill, and real release/deploy/rollback. Round 13 had local build/clean-wheel/Compose evidence, but this round does not treat that prior run as independently re-executed evidence.

## Simplification and stale-state pass

- The latest repairs stay within the existing `WindowToolSearchStore`, `ProviderMetadataStore`, and `PersistenceManager` owners. A generic quota framework would add abstraction without a third materially identical runtime owner, so no new refactor is recommended.
- No obsolete compatibility branch, duplicate state owner, new broad fallback, swallowed core-path error, or test-only implementation shortcut was confirmed in the sampled changes.
- The compatibility report remains Pending and the static checker continues to label 12 groups `Possibly unchanged`; no stale claim of full live compatibility was found in this round.

## Final result

**Clean for new actionable findings.** No new Must Fix or Should Plan issue was confirmed, and no previously accepted debt was repackaged as a new finding. The Draft audit profile and already-recorded live/release/operational gaps remain the limiting evidence.
