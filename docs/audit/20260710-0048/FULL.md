# Codex-Rosetta Audit Ledger

Audit started: 2026-07-10 00:48 MDT  
Repair closed: 2026-07-10 MDT

Profile: `.agent-work/audit/PROFILE.md` (Draft; owner and several security/release baselines remain undefined)

| Area | Status | Severity | Files | Notes |
| --- | --- | --- | --- | --- |
| Repository reality and diff inventory | Reviewed | No Action | repository-wide | HEAD `eb94742`; 86 tracked diff files, 20 untracked files, 4,757 additions / 1,175 deletions; no staged diff |
| Persistent Codex tool-history restoration | Reviewed | No Action | `gateway/proxy.py`, `gateway/tool_adaptation.py`, `observability/persistence.py`, `observability/tool_mapping_crypto.py` | F-01 resolved: exact encrypted SQLite mapping is the cross-request and cross-restart authority |
| Config hot reload and outbound proxy ownership | Reviewed | No Action | `gateway/app.py`, `gateway/proxy.py`, Google converter/content paths | F-02 resolved: app-owned provider proxy is threaded explicitly into URL-image fetches |
| Stream terminal lifecycle and observability | Reviewed | No Action | `gateway/proxy.py`, `gateway/stream_trace.py` | F-03 resolved: completed, error, and cancelled are explicit terminal outcomes |
| Docker and release path | Reviewed | No Action | `docker/docker-compose.yaml`, `docker/Dockerfile`, `Makefile`, release/security docs | F-04 resolved: Compose builds the current checkout wheel and has no registry-image dependency |
| Gateway auth, CORS, app-scoped state, persistence durability | Reviewed | No Action | gateway and observability modules | Prior repairs remain coherent in reviewed paths |
| Responses converter and Codex source contract | Reviewed | No Action | Responses converter, compatibility ledger/script | Local contract gate passed; live matrix remains pending / not approved |
| Test portfolio and independent verification | Reviewed | No Action | `tests/**`, clean-wheel and Compose smoke | Lint/type, 2,533 full tests, compatibility/release, clean-wheel, Compose, and diff checks passed |

## Repository reality and diff inventory

- **Status:** Reviewed.
- **Severity:** No Action for the audit itself; the intentionally dirty worktree was preserved.
- **Scope:** `git status --short --branch`, tracked/staged diff inventory, `HEAD`, and `origin/master..HEAD`.
- **Focus:** Current workspace truth, stale completion claims, and the final repair blast radius.
- **Evidence:** Branch `master` is one commit ahead of `origin/master`; HEAD is `eb947426572ad7658c4b5ad19688fa68659a06b6`. The final unstaged tracked diff covers 86 files with 4,757 additions and 1,175 deletions; 20 files are untracked and there is no staged diff. Audit artifacts are ignored local evidence.
- **Verification:** Direct state/diff inspection and `git diff --check` at repair close.
- **Gaps / Assumptions:** This is not a clean release revision. No user files were reset, reverted, staged, committed, pushed, released, or deployed.

## Persistent Codex tool-history restoration

- **Status:** Reviewed; F-01 resolved.
- **Severity:** No Action after repair; originally Must Fix.
- **Scope:** `src/codex_rosetta/observability/tool_mapping_crypto.py`; mapping schema and operations in `src/codex_rosetta/observability/persistence.py`; persistence ownership in `src/codex_rosetta/gateway/proxy.py`; `tests/gateway/test_persistence_sqlite.py`; `tests/gateway/test_tool_adaptation.py`; EN/ZH gateway-security and code-localization documentation.
- **Focus:** Exact cross-restart replay, single source of truth, at-rest protection, key lifecycle, migration safety, principal isolation, and diagnostic redaction boundaries.
- **Resolved finding:** User selected exact historical replay. Persistent scopes now use SQLite as the authoritative cross-request state and do not use `CodexToolLocalizationStore` as a fallback authority. Operational mappings retain the exact original and Codex-facing calls inside AES-256-GCM ciphertext; diagnostics continue to redact tokens only and are not used to reconstruct executable history.
- **Implementation evidence:**
  - `ToolMappingCipher` stores authenticated payloads with `payload_version`, `key_id`, `nonce`, and `encrypted_payload`; AAD binds principal, provider, model, session, and call ID.
  - The default key is created atomically as `data/tool-mapping.key` with mode `0600` inside a `0700` data directory. A fully fsynced temporary inode is published by a non-overwriting hard link, so concurrent processes converge on one key. `CODEX_ROSETTA_TOOL_MAPPING_KEY` supports an externally managed base64-encoded 32-byte key.
  - Existing encrypted rows make a missing, malformed, wrong, or mismatched key and tampered ciphertext fail closed during persistence initialization. Mapping write failures no longer silently degrade to process memory.
  - Legacy plaintext or `[REDACTED]` mapping rows are removed in an explicit SQLite transaction that replaces only the mapping table; request logs and metrics are preserved. Lossy legacy rows are documented as unrecoverable.
  - Backup/restore documentation requires `gateway.db` and `tool-mapping.key` to move as a pair, or the external secret-manager key to be restored with the database. Key rotation is explicitly not implemented.
- **Verification:** Focused persistence/tool-adaptation regressions passed, including raw SQLite/WAL/SHM plaintext scans, authenticated decrypt equality, same-process and post-restart exact replay, matched DB+key restore, wrong/missing/malformed key, ciphertext tamper, concurrent key creation, transactional legacy migration, TTL/prune, multi-principal isolation, and file permissions. The final full suite passed `2533 passed, 4 skipped, 9 warnings`.
- **Gaps / Assumptions:** No real provider continuation was run. Operators must back up the database and key together; replacing the active key while encrypted rows exist remains unsupported.

## Config hot reload and outbound proxy ownership

- **Status:** Reviewed; F-02 resolved.
- **Severity:** No Action after repair; originally Should Plan.
- **Scope:** `src/codex_rosetta/gateway/app.py`; `src/codex_rosetta/gateway/proxy.py:1576,2424`; `src/codex_rosetta/converters/google_genai/converter.py:254`; `message_ops.py:106-186`; `content_ops.py:117`; converter tests.
- **Focus:** Hot-reload semantics, egress policy, process-global state, and a single app-owned proxy source.
- **Resolved finding:** `create_app()` no longer mutates `HTTP_PROXY` or `HTTPS_PROXY`. `ProviderInfo.proxy_url` is passed through conversion options into Google message/content conversion, and URL-image fetches use that explicit value. A hot-reloaded Gateway config therefore controls provider requests and image fetches consistently without leaking state across app instances.
- **Verification:** Converter regressions assert that the resolved proxy reaches URL-image fetches; lint/type and the full suite passed.
- **Gaps / Assumptions:** No real proxy endpoint or remote image server was used; route selection is covered at the converter boundary.

## Stream terminal lifecycle and observability

- **Status:** Reviewed; F-03 resolved.
- **Severity:** No Action after repair; originally Should Plan.
- **Scope:** converted, raw passthrough, and web-search stream generators in `src/codex_rosetta/gateway/proxy.py`; `src/codex_rosetta/gateway/stream_trace.py`; `tests/gateway/test_stream_trace.py`.
- **Focus:** Cancellation, early close, provider failure, normal EOF, and consistency among trace, metrics, and request log.
- **Resolved finding:** Each stream generator now has one explicit terminal outcome: `completed`, `error`, or `cancelled`. `GeneratorExit` and `asyncio.CancelledError` do not fall through to success. Trace fields `stream_outcome`, `stream_complete`, and `stream_error` agree, while outer request instrumentation retains the 499 disconnect classification.
- **Verification:** Converted, raw, and web-search early-close regressions consume one chunk and close the generator, then assert `stream_outcome=cancelled`, `stream_complete=false`, and the cancellation message. Lint/type and the full suite passed.
- **Gaps / Assumptions:** No real TCP broken-pipe test was required because the exercised `aclose()` path is the same inner-generator cleanup path.

## Docker and release path

- **Status:** Reviewed; F-04 resolved.
- **Severity:** No Action after repair; originally Track as Debt.
- **Scope:** `docker/docker-compose.yaml`; `docker/Dockerfile`; `.dockerignore`; `Makefile:141-145`; `docs/dev/README.md`; `docs/dev/releasing.md`; EN/ZH gateway-security docs.
- **Focus:** Reproducible local deployment, current-checkout provenance, config isolation, and build-context hygiene.
- **Resolved finding:** Versioned Compose no longer references an unpublished registry image. `make compose-up` rebuilds the current checkout wheel, passes `LOCAL_WHEEL`, and starts a local `build:` service. `CODEX_ROSETTA_CONFIG_DIR` allows an isolated config mount. `.dockerignore` excludes `.codegraph/`, `.agent-work/`, and `.agents/` so sockets and audit/agent material do not enter the build context.
- **Verification:** Colima/Compose built and started successfully on the first runtime attempt; `/health/live` returned `{"status":"ok"}`, the container CLI version matched, and encrypted persistence round-tripped inside the container. Alpine installed the `cryptography` musllinux wheel. After the ignore update, the build context dropped from about 21.7 MB to about 1.48 MB with no daemon-socket archive error. Colima was stopped afterward, restoring the initial machine state.
- **Gaps / Assumptions:** This was a local build/smoke, not a registry publish, release, production deploy, or rollback exercise.

## Gateway auth, CORS, app-scoped state, and persistence durability

- **Status:** Reviewed.
- **Severity:** No Action in the sampled paths.
- **Scope:** auth/CORS hooks, Admin JSON validation and activation, `GatewayStateScope`, provider/tool/window stores, SQLite migrations, redaction, and health presentation.
- **Focus:** Authentication ordering, route-specific CORS, principal/window isolation, CAS/rollback, file permissions, cleanup, and secret diagnostics.
- **Evidence:** Protected API routes require a stable principal; preflight does not bypass the real request; Admin origins remain exact allowlist matches; app-owned state roots are cleared on shutdown; config persistence uses digest CAS, owner-only atomic replacement, backup, fsync, and prepare-before-activate.
- **Verification:** Source/diff review and the full suite.
- **Gaps / Assumptions:** The Draft profile excludes a new full Admin/security audit and still lacks several owner/governance baselines.

## Responses converter and Codex source contract

- **Status:** Reviewed.
- **Severity:** No Action for the current automated evidence.
- **Scope:** Responses converter/stream context, namespace/custom/freeform tools, phase buffering, tool-search stores, compatibility ledger and extractor.
- **Focus:** Current Codex contract drift and preservation of tool/stream wire shapes.
- **Evidence / Verification:** `make check-codex-compat` passed at source commit `2e8c3756f95789c215d9ea9a5ade6ec377934b3f`: 14 high-confidence unchanged groups, 12 possibly unchanged groups, and no changed group. `make check-release-version RELEASE_TAG=v0.144.0.r0` passed. The versioned compatibility decision remains **Pending / not approved**.
- **Gaps / Assumptions:** Local `codex-cli 0.144.1` is newer than the `0.144.0.r0` target. Native GPT, the complete agentabi/live Codex/provider matrix, compact/resume/fork, MCP/plugin/deferred tools, WebSocket, browser UI phase, and multi-agent behavior remain unverified or unsupported as recorded in the compatibility report.

## Test portfolio and independent verification

- **Status:** Reviewed.
- **Severity:** No Action for available local gates.
- **Scope:** lint/type, focused high-risk tests, full non-integration suite, clean wheels, Codex contract, release tag, Compose smoke, and diff hygiene.
- **Evidence / Verification:**
  - `conda run -n llm-rosetta make lint`: passed; Ruff check, format check, and `ty check` all green.
  - Focused repair suites passed (`232 passed, 2 warnings`, followed by a `203 passed` regression subset).
  - `conda run -n llm-rosetta make test`: `2533 passed, 4 skipped, 9 warnings` on Python 3.14.6.
  - Clean Python 3.10 and 3.13 wheel smoke: core install/import passed without installing `cryptography`; `[gateway]` install, CLI version, and AES-GCM mapping round-trip passed.
  - `make check-codex-compat`: passed with no changed contract group.
  - `make check-release-version RELEASE_TAG=v0.144.0.r0`: passed.
  - Local Compose/container smoke passed as recorded above.
  - `git diff --check` and `codegraph sync` passed at close.
- **Gaps / Assumptions:** No GitHub Actions run, real provider matrix, browser validation, load/capacity test, dependency vulnerability/license scan, production backup restore, release, deploy, or rollback was performed.

## Simplification pass

- F-01 clarified one operational state owner rather than retaining a second in-memory fallback. Diagnostic redaction and executable mapping storage now have distinct responsibilities.
- F-02 removed process-global proxy duplication instead of adding synchronization logic.
- F-03 uses one terminal outcome value and derives trace flags consistently.
- F-04 reuses the current-wheel Docker contract for Compose; no parallel publishing workflow was added.
- The repair adds one optional gateway dependency (`cryptography`) only where authenticated encryption is required. Core installs remain dependency-free with respect to that package.
