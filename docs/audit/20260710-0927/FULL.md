# Codex-Rosetta Audit Ledger

Audit started: 2026-07-10 09:27 America/Edmonton

Profile: `.agent-work/audit/PROFILE.md` (Draft; audit proceeded because the user explicitly requested an immediate audit)

| Area | Status | Severity | Files | Notes |
| --- | --- | --- | --- | --- |
| Repository state and current diff | Reviewed | No Action | Working tree at `eb94742`; diff from `origin/master` | Large pre-existing working tree preserved |
| Gateway entry points and auth | Reviewed | No Action | `src/codex_rosetta/gateway/auth.py`, `app.py`, auth/header tests | F-01 resolved: the complete `/v1` namespace fails closed |
| Upstream chunked transport | Reviewed | No Action | upstream `zerodep` `httpclient`; vendored `httpclient.py`; Gateway transport/tests | F-02 resolved upstream and officially re-vendored |
| Successful SSE parsing | Reviewed | No Action | upstream `zerodep` `httpclient`/`sse`; vendored copies; Gateway transport/tests | F-03 resolved with line/event limits on converted and raw paths |
| Configuration and Admin credential presentation | Reviewed | No Action | Admin config/diagnostics/UI; bilingual security guide | F-04 accepted semantics: `credential_visible` is API-credential-only |
| Proxy, streaming, and request state | Reviewed | No Action | `gateway/proxy.py`, `stream_phase_buffer.py`, `stream_trace.py`, `state_scope.py` | Terminal outcomes, app roots, persistent state, and phase buffer sampled |
| Persistence, observability, and redaction | Reviewed | No Action | `observability/*`, `gateway/logging.py` | Transactional retention, encrypted mappings, token redaction, and permissions sampled |
| Converter and image paths | Reviewed | No Action | Google/Responses converters, `image_fetch.py`, `image_workers.py` | URL policy, worker ownership, and changed converter contracts sampled |
| Build, release, Docker, and CI | Reviewed | No Action | `pyproject.toml`, `Makefile`, CI, `docker/*`, release scripts | Lint/test/release/wheel/Compose gates passed locally |
| Test portfolio and independent verification | Reviewed | No Action | project and upstream tests | Negative regressions now cover all repaired findings |
| Simplification and agent knowledge | Reviewed | Track as Debt | `AGENTS.md`, docs, changed coordinators | Dead format handlers and large coordinators remain bounded debt |

## Repository state and current diff

- **Scope:** current `master` working tree at `eb947426572ad7658c4b5ad19688fa68659a06b6`, including tracked and untracked changes and the comparison to `origin/master` at `d3e899aea478002d965b0a591fbedf803f80ddb1`.
- **Focus:** repository reality, audit target, preservation of user work, and release readiness.
- **Evidence:** `git status --short`, staged/unstaged/untracked paths, current branch and both revisions were inspected. The final tracked diff contains 95 files, 6,300 insertions, and 1,392 deletions, plus untracked source, tests, scripts, and documentation. Audit repairs were made inside that existing scope without reverting unrelated work.
- **Verification:** `git diff --check` and `git diff origin/master --check` both exited 0. Final `git status --short` was captured, and `codegraph sync` completed successfully (`Synced 9 changed files`).
- **Gaps / assumptions:** `.agent-work/**` is excluded from the production build context and Git status. It intentionally retains audit evidence, clean-wheel environments, the isolated Compose config, and the local upstream checkout.

## F-01: `/v1` authentication fail-open default — Resolved

- **Status / severity:** Resolved; No Action remains.
- **Scope:** `src/codex_rosetta/gateway/auth.py::_is_protected_api_path`, `create_auth_hook`; application wildcard routing; `tests/gateway/test_auth.py`; `tests/gateway/test_app_headers.py`; bilingual Gateway security documentation.
- **Focus:** authentication defaults, dynamic/unknown/removed route safety, browser preflight, and preserved Admin/health behavior.
- **Repair evidence:** `_is_protected_api_path()` now covers `path == "/v1"` and every `path.startswith("/v1/")`. Only `/health`, browser `OPTIONS`, and the separately authenticated Admin surface retain their explicit behavior. Authentication therefore runs before routing for dynamically registered, unknown, and removed `/v1` endpoints.
- **Regression evidence:** tests require 401 for removed and dynamically registered `/v1` paths without a key; an unknown path also returns 401 before routing. With a valid key, the router decides the result. The current wildcard `OPTIONS` route makes an authenticated unknown non-OPTIONS request return 405, which the test records explicitly. Public preflight, Admin authentication, and health behavior remain covered.
- **Verification:** the focused auth/application set passed (`42 passed`), and the full project suite passed.
- **Gaps / assumptions:** no gap remains for the stated fail-closed contract. The authenticated unknown-path 405 is accepted current router behavior rather than an authentication result.

## F-02: peer-declared chunk materialization before the Gateway budget — Resolved

- **Status / severity:** Resolved; No Action remains.
- **Scope:** local upstream checkout `.agent-work/upstream/zerodep`; `httpclient/httpclient.py`; upstream correctness tests; `manifest.json`; vendored `src/codex_rosetta/_vendor/httpclient.py`; `gateway/transport/http/transport.py`; loopback transport tests.
- **Focus:** untrusted upstream resource limits, framing correctness, cancellation/close behavior, and supply-chain provenance.
- **Repair evidence:** upstream `httpclient` moved from `0.4.4` to `0.4.5`. Async chunked decoding now consumes each peer-declared HTTP chunk in caller-selected bounded subchunks instead of issuing one `readexactly(declared_size)`. Gateway bounded body reads request at most 64 KiB, and a small test budget uses `max_bytes + 1`, allowing the outer body cap to reject overflow promptly without materializing the declared chunk.
- **Regression evidence:** real loopback socket tests cover a huge declared chunk whose payload is not fully delivered, normal multi-chunk bodies, oversized body closure, cancellation, and connection closure. The Gateway focused transport/passthrough set passed (`19 passed`).
- **Upstream provenance:** baseline commit `fb84dd10ca736129f937740e44a485034b51258b`; complete six-file upstream diff SHA-256 `62b4be2a13f3b347af40aba37c47fdaf96e60b0bd86fddbaa14d8a13d2d838e0`.
- **Official re-vendor command:**

  ```bash
  python zerodep.py --local update httpclient sse --no-deps \
    --dir /Users/ibobby/Projects/codex-rosetta/codex-rosetta/src/codex_rosetta/_vendor
  ```

- **Vendor verification:** after normalizing only the CLI-managed `# note = ...` header, upstream `httpclient/httpclient.py` and the vendored file are byte-identical. Their normalized SHA-256 is `d1a678cdf403ceae61b7b890aa952178d8bd34014c3c2b94717fba43f40cfedb`.
- **Verification:** upstream HTTP tests passed (`155 passed`); upstream version and dependency checks passed; upstream lint and all pre-commit hooks passed; project lint and full tests passed.
- **Gaps / assumptions:** upstream `make test` cannot complete because the baseline Makefile references absent `jsonc/test_jsonc_correctness.py`. Direct HTTP/SSE suites and repository quality gates pass; this missing baseline file is an upstream aggregate-target validation gap, not a failure introduced by this repair.

## F-03: unbounded successful SSE line/event aggregation — Resolved

- **Status / severity:** Resolved; No Action remains.
- **Scope:** upstream `httpclient/httpclient.py` and `sse/sse.py`; their tests and manifest; vendored copies; `gateway/transport/_base.py`; `gateway/transport/http/transport.py`; converted and raw Responses stream tests; compatibility ledger/checklist.
- **Focus:** long-lived stream reliability, stable errors, byte preservation, and Codex compatibility.
- **Repair evidence:** upstream `sse` moved from `0.3.2` to `0.3.3`; sync/async HTTP lines now default to a 1 MiB byte cap; SSE parsers default to a 1 MiB line cap and an 8 MiB accumulated `data:` payload cap per event. Counters reset at each event delimiter. Overflow and cancellation close the upstream with stable exceptions.
- **Gateway evidence:** `UpstreamStreamLimitError` is the stable Gateway boundary. Converted SSE uses the bounded line/parser interfaces. Raw Responses passthrough tracks the same line/event wire limits without reserializing or otherwise changing valid bytes. Successful streams retain unlimited total duration and total byte count.
- **Regression evidence:** real loopback tests cover a no-newline oversized line and a no-delimiter accumulated event. Focused tests also cover converted overflow, raw passthrough overflow, valid multi-line/events, byte-identical below-limit raw passthrough, cancellation, and close behavior. The focused transport/passthrough set passed (`19 passed`).
- **Vendor verification:** after normalizing only the CLI-managed note header, upstream `sse/sse.py` and the vendored file are byte-identical. Their normalized SHA-256 is `88e25785784c90df278a04d0afeefe0df909a9ac92bf8f8b9bc55aa09c9f526e`.
- **Verification:** upstream SSE tests passed (`76 passed`); `zerodep version-check` passed; `zerodep dep-check httpclient sse` passed (`2 passed`); upstream lint/pre-commit and project lint/full tests passed. Compatibility documentation now records the safety envelope and real-test trigger for future larger Codex events.
- **Gaps / assumptions:** the 1 MiB/8 MiB values are the accepted current safety envelope. A future required Codex/provider event approaching these caps triggers the documented real compatibility test and limit review.

## F-04: proxy URL userinfo under `credential_visible=false` — Accepted Semantics / No Action

- **Status / severity:** Accepted Semantics; No Action.
- **Scope:** Admin config and diagnostics presentation, Admin UI, `docs/en/gateway-security.md`, and `docs/zh-cn/gateway-security.md`.
- **Focus:** precise secret-presentation contract and operator awareness.
- **Evidence:** the accepted product contract is that `server.credential_visible` controls raw Gateway/provider API credential reveal, not arbitrary configuration strings or userinfo embedded in global/provider proxy URLs. Authenticated Admin users can therefore see those connection URLs. Both language guides now state this explicitly and advise keeping proxy passwords out of URLs when possible and protecting Admin access.
- **Verification:** bilingual wording was inspected for semantic parity; the full documentation-containing lint/test gates passed.
- **Gaps / assumptions:** proxy userinfo remains sensitive and visible to an authenticated Admin by design. This is documented residual risk, not an assertion that such URLs are safe to expose outside the Admin trust boundary.

## Reviewed areas with no additional actionable finding

### Proxy, stream terminal lifecycle, and request state

- **Scope / focus:** direct and converted Responses paths, `_InstrumentedStream`, raw/converted/web-search generators, `GatewayStateScope`, metadata/tool/window stores, phase buffer, and application shutdown.
- **Evidence:** terminal completed/error/cancel paths are explicit; application-owned roots are created per app and cleared on shutdown; persistent tool mappings are scoped by principal/provider/model/window and use SQLite authority; phase buffering is bounded after event parsing.
- **Verification:** source/CodeGraph inspection and the passing full test suite; F-02/F-03 close the earlier transport/parser boundary gaps.
- **Gaps:** real client disconnect and provider streams were not exercised in this audit.

### Configuration activation, persistence, and observability

- **Scope / focus:** config digest CAS, lock/backup/restore, runtime prepare/activate/rollback, retention transactions, request/error logs, token redaction, encrypted tool mappings, and file permissions.
- **Evidence:** writes are locked and atomically replaced; activation has compensation state; retention pruning is transactional; mapping ciphertext is AES-GCM authenticated to ownership coordinates; diagnostics apply the documented token-only redactor; storage permissions are owner-only.
- **Verification:** source inspection and persistence/config/security coverage in the passing full suite.
- **Gaps:** no multi-process config/persistence stress, restore drill, or key-rotation implementation was exercised.

### Converter, image egress, and Codex compatibility

- **Scope / focus:** changed OpenAI Responses typing/passthrough logic, Google URL-image conversion, SSRF policy, worker capacity, tool adaptation, and compatibility ledger/checker.
- **Evidence:** image URLs are HTTP(S)-only and public-address validated; direct connections are numeric-address pinned; redirect/MIME/byte limits exist; application-owned worker capacity is bounded; changed converter paths have focused tests.
- **Verification:** `make check-codex-compat` passed against source commit `2e8c3756f95789c215d9ea9a5ade6ec377934b3f` with no changed contract group. The compatibility ledger and upgrade checklist include the repaired stream limits.
- **Gaps:** every possibly-unchanged compatibility point still requires its documented real Codex/API test before a future compatibility acceptance; no live public image/provider test ran.

### Build, release, Docker, CI, and agent knowledge

- **Scope / focus:** current-wheel Docker provenance, disabled publish targets, release-tag check, Python CI matrix, `.dockerignore`, repository instructions, and compatibility documentation.
- **Evidence:** Docker consumes a wheel built from the current checkout; agent/audit/codegraph paths are excluded; publishing targets fail closed; CI covers Python 3.10/3.13. `make check-release-version RELEASE_TAG=v0.144.0.r0` passed.
- **Clean-wheel smoke:** isolated Python 3.10.20 and 3.13.2 core and Gateway environments import successfully and report `0.144.0.r0`; both Gateway CLIs report `codex-rosetta-gateway 0.144.0.r0`. The preserved smoke wheel and current `dist` wheel have identical member names and member contents; archive hashes differ only because the wheel was rebuilt with new ZIP metadata.
- **Compose runtime smoke:** image `codex-rosetta-gateway-local:0.144.0.r0` (`sha256:992a76bd1a27c7823d5cd516fc5bc84323e77040ec66c4a96c32c3f35ec7b4e1`) was run with isolated config `.agent-work/compose-smoke/config-20260710` and host port `18765`. `GET /health` returned `status: ok`, and the in-container CLI reported `0.144.0.r0`. Only that temporary container and project network were removed. The pre-existing process on `127.0.0.1:8765` was not touched.
- **Debt:** unused legacy generation handler functions remain in `gateway/app.py`; `app.py`, `proxy.py`, and Admin config coordination are large. Their current boundaries are documented and tested enough that a broad rewrite is not justified by this audit.

## Independent verification

- Main repository `make lint`: passed.
- Main repository `make test`: passed (`2632 passed, 4 skipped, 9 warnings`).
- Focused auth/application tests: passed (`42 passed`).
- Focused transport/raw-passthrough tests: passed (`19 passed`).
- `make check-codex-compat`: passed; no changed contract group.
- `make check-release-version RELEASE_TAG=v0.144.0.r0`: passed.
- Clean Python 3.10/3.13 wheel core/Gateway smokes: passed and re-inspected.
- Current-wheel Compose image build and isolated runtime smoke: passed.
- Upstream `httpclient`: `155 passed`; upstream `sse`: `76 passed`; version check, dependency check (`2 passed`), lint, Ruff/format/ty/complexipy pre-commit hooks: passed.
- Upstream complete diff hash and normalized vendor/source equality: passed.
- Final `git diff --check` and `git diff origin/master --check`: passed (exit 0); `git status --short` was captured; `codegraph sync` passed (`Synced 9 changed files`).
- Audit lifecycle: final `FULL.md` and `REPORT.md` are present and `.agent-work/audit/CURRENT.md` was removed.
- Not run: `tests/integration/**`, real Codex/provider/agentabi matrix, remote CI, release/deploy, backup/restore drill, or multi-process stress. Release/deploy/commit/push/PR were outside the authorized scope.
- Upstream aggregate `make test`: blocked by the baseline Makefile's missing `jsonc/test_jsonc_correctness.py`; direct changed-module tests and repository quality gates passed.

## Simplification pass

- F-01 was resolved at the namespace policy boundary instead of maintaining a second positive route list.
- F-02/F-03 were resolved once in upstream `zerodep`, then officially re-vendored; the Gateway adds only product-specific budgets and stable error translation.
- Raw passthrough uses a local byte tracker because byte preservation forbids decode/re-encode through the converted SSE parser; the two paths share the same constants and error type.
- F-04 required contract clarification rather than a masking subsystem; no unused abstraction was added.
- No broad coordinator refactor is required. Legacy unused handlers and large coordinators remain bounded debt for a separately scoped cleanup.
