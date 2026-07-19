# Audit Ledger — 2026-07-11 01:52

Audit profile: `.agent-work/audit/PROFILE.md` (Draft)

| Area | Status | Severity | Files | Notes |
| --- | --- | --- | --- | --- |
| Repository state and Round 21 repairs | Reviewed | No Action | `git status`, `e48f9b1..HEAD`, dirty analyzer diff | Five prior repair commits and the later dirty analyzer diff were inspected separately |
| Gateway ingress, auth, routing, and state | Reviewed | No Action | `gateway/app.py`, `gateway/embeddings.py`, `gateway/proxy.py`, `gateway/auth.py`, state stores | F-02 resolved in `18eb243`; invalid model values now return source-shaped 400 responses |
| Converters and Codex compatibility | Reviewed | Track as Debt | `src/codex_rosetta/converters/**`, compatibility ledger/tests | Automated contract and stream ordering pass; credentialed live matrix remains pending |
| Persistence and observability | Reviewed | No Action | `src/codex_rosetta/observability/**`, Admin persistence | Encrypted SQLite tool history remains authoritative and restart-safe; scope isolation sampled |
| Analyzer and developer tooling | Reviewed | No Action | `scripts/analyze_codex_jsonl_errors.py`, `Makefile`, CI | F-01 resolved in `9e61807`; ordinary secret fields are preserved while token boundaries remain masked |
| Build, release, Docker, and supply chain | Reviewed | No Action | `.github/**`, `docker/**`, package metadata | Manual GitHub-only release and current-wheel Docker boundaries remain enforced |
| Tests and independent verification | Reviewed | No Action | `tests/**`, project gates | Post-repair focused and full suites plus all local gates pass |
| Simplification and stale-state pass | Reviewed | Track as Debt | gateway coordinators, analyzer, compatibility docs | Existing ratcheted hotspots and pending live baseline remain visible; no broad rewrite recommended |

## Audit framing

- Current branch: `audit/20260711`; initial HEAD: `2c29d36 feat(analyzer): add evidence-aware JSONL failure analysis`; repair closure HEAD: `18eb243 fix(gateway): reject invalid model values`.
- Initial working tree: unstaged modifications in `scripts/analyze_codex_jsonl_errors.py` and `tests/test_analyze_codex_jsonl_errors.py`.
- Baseline: `e48f9b1` (`origin/master` at audit start); Round 21 added five repair commits through `2c29d36`.
- Profile status: Draft. Unknown owner decisions remain legal/privacy constraints, vulnerability response, SLOs, CI credential boundaries, release signing, and SBOM expectations.
- Quality priorities: correctness and reliability first; then security, operability/modifiability; then performance and cost.
- Profile exclusions are treated as sampling limits rather than a prohibition: generic converters, Admin UI, deployment, and dependencies are sampled where risk or recent change justifies it.

## Repository state and Round 21 repair closure

- `git status --short --branch` showed `audit/20260711` at `2c29d36` with only two unstaged paths: `scripts/analyze_codex_jsonl_errors.py` and `tests/test_analyze_codex_jsonl_errors.py`.
- The committed range from `e48f9b1` through `2c29d36` contains the stats I/O isolation, embeddings stats, analyzer static checks, complexity ratchet, and session/trace analyzer split described by Round 21. Each commit message contains `Maintenance-Audit: true` exactly once.
- The unstaged diff adds `provider_like` aggregation and its focused test (128 insertions, 1 deletion). It was reviewed as current working-tree behavior but was not attributed to the Round 21 commit verification.
- Focused current-tree verification for analyzer, stats logging, and embeddings returned **38 passed**.

## F-01 — Diagnostic analyzer redacts generic `secret=` values beyond the settled token-only boundary

- **Status:** Resolved in `9e61807`.
- **Severity:** Should Plan.
- **Scope:** `scripts/analyze_codex_jsonl_errors.py:54-59`, `redact_text()`, analyzer tests.
- **Trigger:** Analyze an otherwise reportable error containing an assignment such as `secret=ordinary-secret` or `client_secret=ordinary-client-secret`.
- **Pre-fix evidence:** `SENSITIVE_ASSIGNMENT_RE` explicitly included the unqualified alternative `secret`. The runtime persistence tests establish the current business boundary by preserving ordinary `secret`/`client_secret` values while redacting configured tokens, API keys, Bearer values, and Authorization values (`tests/gateway/test_persistence_sqlite.py:216-301`, `:1197-1238`). Before `9e61807`, the analyzer had only a Bearer regression and no ordinary-secret preservation regression.
- **Impact:** Historical diagnostics silently discard non-token data that the owner explicitly chose to retain, reducing forensic fidelity and making analyzer output inconsistent with gateway persistence.
- **Fix direction:** Remove the unqualified `secret` assignment alternative while retaining `authorization`, API-key, `*token`, Bearer, configured key-shape behavior; add explicit preservation and redaction tests. Do not broaden this repair into changing signature aggregation placeholders.
- **Resolution:** The unqualified `secret` alternative was removed. A behavior regression preserves ordinary `secret` and `client_secret` while proving access-token, API-key, Authorization, and Bearer values are still masked. The pre-existing `provider_like` working-tree hunks were excluded from the commit.

## F-02 — Non-string request models can surface as 500-class internal errors

- **Status:** Resolved in `18eb243`.
- **Severity:** Should Plan.
- **Scope:** `src/codex_rosetta/gateway/proxy.py:204-206`, `src/codex_rosetta/gateway/app.py:495-519`, `src/codex_rosetta/gateway/embeddings.py:66-91`.
- **Trigger:** Send a JSON object with a truthy non-string model, for example `{"model":["x"],"input":"hello"}` to `/v1/embeddings`; equivalent proxy endpoints reach the same routing lookup through `extract_model()`.
- **Pre-fix evidence:** `extract_model()` returned `body.get("model")` despite its `str | None` annotation. Both handlers only checked truthiness and then passed the value to `GatewayConfig.resolve()`, whose dictionary lookup rejects a list as unhashable. A direct pre-fix reproduction raised `TypeError: cannot use 'list' as a dict key (unhashable type: 'list')` instead of returning an API-shaped 400 response.
- **Impact:** Untrusted invalid input bypasses the normal client-error contract and can produce noisy 500s without the expected pre-resolution telemetry path. It does not currently expose data or crash the process.
- **Fix direction:** Enforce a non-empty string at the shared model extraction boundary and use the same check for embeddings; return the existing source-shaped 400 invalid-request response. Add both proxy and embeddings regressions.
- **Resolution:** `extract_model()` now rejects non-string and blank values. Both `/v1/responses` and `/v1/embeddings` return `invalid_request_error` with HTTP 400 for list, object, number, boolean, empty-string, and whitespace-only inputs; missing-model behavior and valid alias behavior remain covered.

## Auth, state isolation, and persistent history

- Admin password and gateway API keys remain mandatory through config validation and generated starter config. `/v1/**` authentication runs in both the pre-body and pre-request hooks.
- `GatewayStateScope` includes the authenticated principal plus provider/model/conversation identity. Metadata, deferred-tool, and localization stores are scoped by that value, preventing same-window/call-id reuse across API principals.
- Persistent localized tool history is queried from encrypted SQLite before request-history rewriting. Persistent response mappings are written through `_persist_tool_mapping()` and are deliberately not stored in `CodexToolLocalizationStore`; persistence absence, key mismatch, invalid authenticated rows, and write failure fail closed instead of falling back to volatile state.
- Restart, key backup/restore, ciphertext tamper, principal isolation, TTL, and hierarchical capacity cases are covered in `tests/gateway/test_persistence_sqlite.py`. No new violation of the replay-first / SQLite-authoritative requirement was found.

## Converters, streaming, and Codex compatibility

- The high-risk Responses SSE path was traced through converter event dispatch, gateway stream conversion, `ResponsesPhaseBuffer`, stream finalization, and persistent tool-history rewrite.
- Existing tests exercise `response.created` → output item added → delta → item done → `response.completed`, message phase consistency, reasoning/custom tool calls, native `tool_search_call`/`web_search_call`, completed-only fallback, Chat EOF finalization, cancellation, and stream telemetry cleanup.
- `make check-codex-compat` matched source commit `2e8c3756f95789c215d9ea9a5ade6ec377934b3f`; every high-confidence contract matched, the explicitly partial structural groups remained "Possibly unchanged", and `Changed: None`.
- The compatibility ledger correctly remains pending rather than claiming live approval. Credentialed native/cross-provider Codex, agentabi, compact/resume, collaboration, and full tool-search behavior were not rerun in this audit.
- No new concrete converter/stream mismatch was demonstrated. The live-matrix gap remains tracked debt, not a newly resolved capability.

## Build, release, Docker, and supply chain

- Current `.github/workflows/` contains CI, a weekly/manual SDK monitor, and Docker safety; there is no automated release or publish workflow.
- `push-package`, `push-docker`, and `push` remain disabled. `docs/dev/releasing.md` requires manual GitHub UI release and `v{source_version}` tag spelling.
- `make check-release-version RELEASE_TAG=v0.144.0.r0` passed against source `0.144.0.r0`.
- Docker and Compose require `LOCAL_WHEEL` produced by the current checkout. The Dockerfile copies only `dist/`, installs the named wheel, drops to `appuser`, and uses `/config` for persistent state. It has no PyPI package fallback and no registry push path.
- A wheel build succeeded: `dist/codex_rosetta-0.144.0.post0-py3-none-any.whl`.
- Unknown profile decisions remain action pinning/signing, SBOM, vulnerability response, and CI credential policy. No unsupported assurance is made for them.

## Independent verification

- Pre-repair changed-area focused group: **38 passed**.
- Post-repair focused group: **68 passed**.
- Post-repair full current-tree suite: **2842 passed, 5 skipped, 9 warnings** in 14.49s on Python 3.14.6.
- `make lint`: Ruff passed, 299 files formatted, `ty check` passed, and the Complexipy snapshot ratchet passed.
- Codex source contract: passed at `2e8c3756f95789c215d9ea9a5ade6ec377934b3f`, `Changed: None`.
- Manual release tag check: passed for `v0.144.0.r0`.
- Wheel build: passed and produced `codex_rosetta-0.144.0.post0-py3-none-any.whl`.
- `git diff --check` and `git diff --cached --check`: passed.
- Final verification state has an empty index and only the two preserved pre-existing analyzer/test unstaged modifications (128 insertions, 1 deletion). No `provider_like`, `DIRECT_PROVIDER_STATUS`, `summarize_provider_like`, `PROVIDER_LIKE_CATEGORIES`, or `EXPLICIT_HTTP_STATUS` hunk entered `9e61807`; all remain visible in the unstaged diff.
- Not run: credentialed live providers/Codex/agentabi, external GitHub Actions, Admin browser smoke, Docker daemon build/smoke, vulnerability/license/SBOM/signing scans, production deploy/rollback, backup restore rehearsal, hostile proxy/DNS, and load testing.

## Simplification and stale-state pass

- The two confirmed repairs should remain local: narrow the analyzer credential regex and centralize request-model type validation without adding a new validation framework.
- The dirty `provider_like` summary derives from existing grouped evidence and does not authorize failover; no second scanner or parallel parser abstraction was introduced.
- The complexity ratchet exposes existing coordinator/converter hotspots without forcing a risky broad rewrite. Future cleanup should follow changed hotspots and protective stream tests.
- The dated compatibility report still identifies a dirty pending snapshot; it is explicitly marked pending and should be refreshed only with a complete clean live acceptance run.
- No safe deletion or abstraction merge beyond the two local findings is justified by current evidence.

## Repair follow-up

| Finding | Status | Commit | Verification |
| --- | --- | --- | --- |
| F-01 token-only analyzer redaction | Resolved | `9e61807` | Ordinary `secret`/`client_secret` retained; token/API-key/Authorization/Bearer masked; provider-like WIP excluded |
| F-02 invalid request model boundary | Resolved | `18eb243` | Both public POST endpoints return 400 for list/object/number/bool/blank values and retain missing-model behavior |

Both commits contain exactly one `Maintenance-Audit: true` trailer. No push,
PR, release, publish, or deployment action was performed.
