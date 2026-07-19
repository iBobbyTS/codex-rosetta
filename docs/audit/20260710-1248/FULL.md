# Full Audit Ledger

Audit opened: 2026-07-10 12:48 MDT  
Audit repair closed: 2026-07-10 14:02 MDT  
Profile: `.agent-work/audit/PROFILE.md` (Draft)  
Scope: Current repository state, with priority on Codex compatibility contracts, gateway state/concurrency, trust boundaries, persistence/observability, release integrity, and test quality.

| Area | Status | Severity | Files | Notes |
| --- | --- | --- | --- | --- |
| Repository reality and change surface | Reviewed | No Action | working tree, recent commits, diff | 97 tracked files plus 30 untracked files; no staged diff; user work preserved |
| Codex request/response compatibility | Reviewed | No Action | `converters/openai_responses/`, `tool_ops.py`, compatibility docs/scripts | Static contract and full unit suite pass; live matrix remains required |
| Gateway state ownership and quotas | Reviewed | No Action | `gateway/proxy.py`, `gateway/state_scope.py` | F-01 and F-02 resolved with principal-fair hard quotas and regression coverage |
| Persistent executable tool mappings | Reviewed | No Action | `observability/persistence.py`, `gateway/tool_adaptation.py`, `gateway/app.py` | F-03 resolved with hierarchical row/byte caps, encrypted-v1 migration, bounded replay, and transactional accounting |
| Streaming, transport, and image fetching | Reviewed | No Action | gateway stream/transport/image paths, `_vendor/**` | Bounded local envelopes and lifecycle reviewed; no new issue beyond known total-stream limitation |
| Auth, Admin, config, and diagnostics | Reviewed | No Action | auth/CORS/admin/config/observability | Existing negative boundaries and documented residual-data policy reviewed |
| Release, Docker, CI, and vendoring | Reviewed | Track as Debt | `pyproject.toml`, Makefile, Docker, CI, upstream ledger | Local build, clean-wheel, Compose, version, and compatibility gates pass; external CI/live release/provenance remain manual |
| Test portfolio and independent verification | Reviewed | No Action | `tests/`, lint/test/build/compat commands | 2717 passed, 4 skipped; lint/type, build, release, wheel, Compose, and static compatibility gates pass |

## Audit framing

- Highest priorities: correctness and reliability of Codex protocol translation; security of credentials and persisted model/tool traffic; principal-fair resource ownership; modifiability of compatibility contracts.
- Repository profile exclusions: full dependency/security/admin UI/generic converter audit are not exhaustive, but current uncommitted changes in those areas remain in scope where they affect Codex/gateway risk.
- Profile gaps: legal/privacy constraints, ASVS target, vulnerability response, CI permission baseline, artifact signing, SLOs, and owner are unconfirmed.
- Repository evidence: branch `master` at `eb947426572ad7658c4b5ad19688fa68659a06b6`; the broad dirty worktree belongs to the user and was preserved.

## Repository reality and final change surface

- Final state: 97 modified tracked files and 30 non-ignored untracked files. `git diff --shortstat` reports 9,018 insertions and 1,597 deletions. There is no staged diff.
- High-churn paths sampled in detail: `gateway/proxy.py`, `gateway/app.py`, `gateway/config.py`, Admin config activation, HTTP transport/vendor, observability persistence/crypto, Google image fetching, CI/Docker/release scripts, and associated tests.
- `_vendor/httpclient.py`, `_vendor/httpserver.py`, and `_vendor/sse.py` were previously compared to the local upstream zerodep worktree. The audit repair did not modify those files or revert user work.
- `git diff --check` passes. `codegraph sync` completed after the six repair-related code/test files changed.
- Compose verification generated `docker/config/` only for the smoke run; the container/network were stopped and removed, and the generated untracked config/database directory was deleted after inspection.

## F-01 — WindowToolSearchStore cross-principal eviction

- **Status / severity:** Resolved; `No Action` after repair verification.
- **Original risk:** A global loaded/deferred map at `max_size` could evict another authenticated principal's oldest scope, silently breaking deferred-tool continuity.
- **Repair:** `WindowToolSearchStore` now accounts unique scopes across loaded and deferred maps with `scope_refs` and `principal_scopes`. A principal has a hard default limit of 256 unique scopes. A scope present in both maps counts once. Reaching the principal cap rejects before mutation. When a per-map global count is full, `_planned_evictions_locked()` may select only the inserting principal's oldest scope; if no same-principal candidate exists, it rejects without touching other principals. TTL, replacement, eviction, scoped clear, root clear, and accounting rebuild return the scope count and bytes.
- **Evidence:** `src/codex_rosetta/gateway/proxy.py::WindowToolSearchStore`; `tests/gateway/test_window_tool_search_store.py` covers combined loaded/deferred counting, hard principal rejection, other-principal headroom, same-principal oldest eviction, cross-principal rejection, concurrent saturation, TTL, and clear accounting. Existing request lifecycle coverage confirms capacity errors map to 413 and persistent windows retain continuity.
- **Verification:** Repair-focused suite passed; expanded gateway/persistence suite passed with 293 tests; full non-integration suite passed.

## F-02 — ProviderMetadataStore principal monopolization

- **Status / severity:** Resolved; `No Action` after repair verification.
- **Original risk:** One principal could consume all 10,000 small entries even though byte limits and eviction were otherwise principal-isolated.
- **Repair:** `ProviderMetadataStore` now enforces a hard default limit of 1,024 entries per principal under the existing shared lock. Batch and replacement projections count only genuinely new keys, so replacement does not double count. Global count overflow can evict only the inserting principal's oldest non-candidate entry; no cross-principal eviction is allowed. TTL, scoped clear, root clear, and replacement return entry/byte accounting.
- **Evidence:** `src/codex_rosetta/gateway/proxy.py::ProviderMetadataStore`; `tests/gateway/test_provider_metadata_store.py` covers hard principal rejection, another principal retaining capacity, same-principal oldest eviction, replacement at the cap, atomic batch rejection, TTL/clear, and concurrent saturation.
- **Verification:** Repair-focused suite passed; expanded gateway/persistence suite passed with 293 tests; existing request lifecycle coverage confirms stable 413 mapping.

## F-03 — Unbounded encrypted tool-history persistence

- **Status / severity:** Resolved; `No Action` after repair verification.
- **Original risk:** Authenticated clients could create unlimited encrypted mapping rows/bytes and replay an unbounded session into memory, ultimately exhausting the shared SQLite filesystem or process memory.
- **Repair:** `PersistenceManager` now enforces fixed defaults of 16 MiB per row; 2,048 rows/64 MiB per session; 8,192 rows/256 MiB per principal; and 32,768 rows/512 MiB globally. The schema stores `mapping_bytes` and indexes principal/session ownership. Existing encrypted-v1 tables receive an in-place column/index backfill without decrypting or deleting valid rows; unrecoverable plaintext/lossy legacy rows retain their documented discard contract. Startup validates accounting and all hierarchy caps before batched authentication. Query validates the session envelope and accounting before loading/decrypting rows. Upsert uses the persistence owner's `RLock` and one `BEGIN IMMEDIATE` transaction for expiry cleanup, replacement-aware projection, validation, and write; any capacity or SQLite failure rolls back cleanup and preserves the old row.
- **Evidence:** `src/codex_rosetta/observability/persistence.py`, public `ToolMappingCapacityError` export in `observability/__init__.py`, and `tests/gateway/test_persistence_sqlite.py`. New tests cover row/session/principal/global rows and bytes, replacement without double counting, rejection preserving the prior row, expiry budget release, cross-principal/global saturation, concurrent no-oversell, raw SQLite accounting, encrypted-v1 backfill, abnormal oversized replay rejection, and simulated SQLite write rollback. Existing tests continue to cover wrong/missing keys and tampered ciphertext.
- **Verification:** Repair-focused suite passed; expanded gateway/persistence suite passed with 293 tests; restart, migration, rollback, and full-suite coverage passed.

## Documentation and compatibility ledger

- English source-of-truth and Chinese counterpart were updated together in `docs/en/gateway-security.md` and `docs/zh-cn/gateway-security.md` with principal-fair in-memory quotas, encrypted mapping budgets, transaction semantics, migration, and fail-closed behavior.
- `docs/dev/version-compatibility/compatibility-points.md` and `upgrade-checklist.md` now record the new Codex-facing quota/accounting contracts and both automated and real-session upgrade tests.
- The repair stays within the existing `WindowToolSearchStore`, `ProviderMetadataStore`, and `PersistenceManager` ownership boundaries. It does not add a parallel cache or persistence service.

## Independent verification

- Repair-focused quota/fairness suite: **117 passed**.
- Expanded state/persistence/config suite: **293 passed**.
- `make lint`: passed; Ruff check, Ruff format check, and `ty check` all passed.
- `make test`: passed; **2717 passed, 4 skipped, 9 warnings** in 17.00 seconds.
- `make build`: passed; source archive and `codex_rosetta-0.144.0.post0-py3-none-any.whl` built.
- `make check-codex-compat`: passed against Codex source commit `2e8c3756f95789c215d9ea9a5ade6ec377934b3f`; Changed: None; 12 groups remain explicitly `Possibly unchanged`.
- `make check-release-version RELEASE_TAG=v0.144.0.r0`: passed.
- Clean-wheel smoke: Python 3.10 and 3.13 both passed core import, Google converter import, gateway import, and `codex-rosetta-gateway --version` (`0.144.0.r0`).
- `make compose-up`: rebuilt the current checkout wheel, built image `codex-rosetta-gateway-local:0.144.0.r0`, started the gateway, and returned HTTP 200 from `/health`; the smoke stack was then removed.
- `git diff --check`: passed.
- `codegraph sync`: passed; six changed files indexed.
- Not run: `tests/integration/**`, real provider/API/agentabi/live Codex, browser Admin, external GitHub Actions, load/capacity benchmarks at production scale, vulnerability/license scanning, recovery drill, real release/deploy/rollback.

## Simplification and remaining follow-up

- The three repairs establish a consistent local rule: authenticated principals are both data-isolation and resource-ownership boundaries. The rule is documented and enforced in the three existing owners without a new generic quota framework.
- Complexity is localized to accounting dictionaries in the two in-memory stores and transaction/query helpers in the existing persistence owner. Tests exercise mutation, rollback, expiry, clear, concurrency, and migration rather than only implementation details.
- No follow-up refactor is recommended for these repairs. The Draft audit-profile gaps remain: owner, legal/privacy baseline, ASVS target, SLO/error budget, incident response, signing/SBOM, dependency governance, and CI permission policy.
- Live Codex/provider evidence and external CI remain required before claiming full Codex `0.144.0` compatibility or publishing a release.
