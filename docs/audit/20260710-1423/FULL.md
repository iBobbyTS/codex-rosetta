# Full Audit Ledger

Audit opened: 2026-07-10 14:23 MDT  
Audit closed: 2026-07-10 14:49 MDT  
Profile: `.agent-work/audit/PROFILE.md` (Draft)  
Scope: Independent round 15 review of the current uncommitted repository state, emphasizing gateway trust boundaries, Admin browser rendering, inbound HTTP safety, Codex state ownership, and verification integrity.

| Area | Status | Severity | Files | Notes |
| --- | --- | --- | --- | --- |
| Repository reality and change surface | Reviewed | No Action | working tree, diff, prior audit ledgers | 97 tracked modified files plus 31 non-ignored untracked files; no staged diff; user work preserved |
| Cross-request state and persistence | Reviewed | No Action | `gateway/state_scope.py`, `gateway/proxy.py`, lifecycle/persistence tests | Prior quota and lifecycle boundaries sampled; no new defect confirmed |
| Inbound HTTP and forwarded request headers | Reviewed | Track as Debt | vendored `httpserver.py`, `gateway/app.py`, `gateway/headers.py` | Request/header aggregate envelopes exist; client correlation fields are not normalized but no high-impact exploit confirmed in this pass |
| Admin model-test browser rendering | Reviewed | No Action | `gateway/admin/admin.html`, `tests/gateway/test_admin_page_routes.py`, `tests/gateway/test_admin_model_usage_browser.py` | F-01 resolved with text-only DOM rendering, strict token validation, and a real Chromium regression |
| Verification | Reviewed | No Action | targeted tests, real Chromium, live Admin, full gates, Compose | 2,723 tests collected; 2,718 passed and 5 skipped; browser, package, compatibility, release-version, and container smoke gates pass |

## Audit framing

- Highest-priority attributes: security, protocol correctness, cross-request isolation, reliability, and maintainability.
- The Draft profile leaves legal/privacy, ASVS, SLO, incident response, signing/SBOM, and dependency-governance decisions open.
- The independent review began read-only. After F-01 was adjudicated as self-fixable, the repair stayed local to the Admin page and regression tests; no new runtime dependency or frontend framework was introduced.

## Repository reality

- Branch: `master`, one commit ahead of `origin/master`; HEAD `eb94742`.
- Final non-ignored working tree: 97 tracked modified files and 31 untracked files; no staged diff. The tracked diff contains 9,091 insertions and 1,610 deletions.
- `git diff --check` passed before repair and again after the final ledger update. `codegraph sync` completed successfully and indexed the seven files changed in this round.
- Prior ledgers were read to avoid duplicating already repaired or explicitly accepted findings. Current source remains authoritative.

## Cross-request state and persistence resampling

- Rechecked authenticated principal/window ownership, request-local cleanup, persistent window scopes, and the latest provider-metadata/tool-search quota owners.
- Current code still keeps cleanup and capacity enforcement inside the existing state owners, with the negative and lifecycle tests introduced by prior rounds present in the full suite.
- No distinct new state, persistence, or quota defect was confirmed.

## Inbound HTTP and request-header boundary

- Vendored `httpserver.py` bounds inbound body size to 1 MiB, header count to 100, aggregate headers to 64 KiB, and one header section to a 10-second deadline.
- Client `x-request-id`, `User-Agent`, and `OpenResponses-Version` values are forwarded without a dedicated field-value normalizer; `x-request-id` is also echoed and logged. Newline framing prevents an ordinary CRLF value from surviving as one parsed header, and the aggregate header budget limits size. This pass did not confirm a high-impact response-splitting or resource-exhaustion path, so it is not elevated to a new actionable finding.
- The server still returns 500 for some syntactically invalid transfer-length inputs, but each connection is closed and no cross-request desynchronization path was confirmed. This remains minor protocol-hardening debt rather than a report finding.

## F-01 — Admin model-test usage rendering permits upstream-controlled DOM XSS (resolved)

- **Status / severity:** Resolved / No Action.
- **Original scope:** the pre-repair `runTest()` metadata sink in `src/codex_rosetta/gateway/admin/admin.html`, plus raw provider results returned by `gateway/admin/routes/testing.py` and `gateway/embeddings.py`.
- **Focus:** Browser trust boundary, external provider response handling, Admin credential exposure, defense in depth, tests.
- **Original finding:** Before repair, the non-streaming Admin model-test renderer concatenated `body.usage.prompt_tokens`, `input_tokens`, `output_tokens`, and `completion_tokens` directly into `meta.innerHTML`. These fields were not validated or escaped at the sink.
- **Original trigger:** An embedding/Responses provider could return a successful JSON body whose usage field contained markup, for example `prompt_tokens: "<img src=x onerror=...>"`; running the Admin model test then crossed the provider-to-DOM boundary. The embedding path remains an intentional raw passthrough, while the UI sink now treats its result as untrusted text.
- **Original impact:** The injected event handler would have executed in the Admin origin. `admin_token` is stored in `localStorage` and attached to privileged Admin requests, so the pre-repair sink could have escalated a malicious provider response into Admin session takeover and gateway credential/config compromise.
- **Defense-in-depth gap:** The Admin page CSP is still only `frame-ancestors 'none'`; it does not define `default-src` or `script-src`. This no longer leaves an open F-01 sink but remains relevant to future frontend threat modeling.
- **Pre-repair evidence:** The reviewed pre-repair diff had direct provider-value interpolation into `meta.innerHTML`; `embeddings.py` and the Admin testing task returned the successful upstream JSON without coercing usage fields. The current diff replaces that sink as described below.
- **Repair:** `admin.html:4118-4165` now builds metadata with `createElement`, `textContent`, `createTextNode`, and `replaceChildren`. `_safeUsageCount()` accepts only non-negative `Number.isSafeInteger()` values; strings, objects, arrays, coercion hooks, `NaN`, infinities, negative values, and unsafe integers render as `-`. `_usageCount()` preserves provider fallbacks only when the primary key is absent, so an invalid primary value cannot smuggle content through a fallback. All `runTest()` metadata writes use these helpers; no `meta.innerHTML` sink remains.
- **Automated regression:** `tests/gateway/test_admin_page_routes.py:112` asserts the safe-by-construction sink contract. The opt-in real-browser test at `tests/gateway/test_admin_model_usage_browser.py:47` exercises embedding, Responses, OpenAI Chat fallback, Anthropic, and Google usage shapes with HTML/SVG/script-closing payloads, Unicode/control text, objects, arrays, coercion hooks, `NaN`, infinities, negatives, and unsafe integers.
- **Real-browser result:** `RUN_ADMIN_BROWSER_TESTS=1 conda run -n llm-rosetta python -m pytest tests/gateway/test_admin_model_usage_browser.py -vv -s` passed in Chromium `149.0.7827.201` with `DOM_ASSERTIONS_OK`. The DOM contained no injected `img`, `svg`, or `script`; event execution, Admin-token reads, stubbed fetch exfiltration, and custom coercion all remained zero. The harness requires the success marker and browser version and rejects Playwright `### Error` or `SyntaxError` output, preventing the earlier false-green CLI invocation shape.
- **Residual note:** The Admin CSP remains limited to anti-framing. A future nonce/hash CSP would add defense in depth, but the exploitable provider-controlled HTML sink itself is removed and covered by a browser regression.

## Verification

- `conda run -n llm-rosetta make lint`: passed; Ruff check, Ruff format check (291 files), and `ty check` passed.
- `conda run -n llm-rosetta make test`: passed; **2,723 collected, 2,718 passed, 5 skipped, 9 warnings** in 18.01 seconds. The new opt-in browser module accounts for the additional ordinary pass and default skip relative to the pre-repair 2,717/4 result.
- `RUN_ADMIN_BROWSER_TESTS=1 conda run -n llm-rosetta python -m pytest tests/gateway/test_admin_model_usage_browser.py -vv -s`: passed with `DOM_ASSERTIONS_OK` under Chromium `149.0.7827.201`.
- Live Admin smoke: a real gateway instance loaded the login flow and `/admin/providers` in headed Chromium, preserved the Admin token in `localStorage`, and returned `Content-Security-Policy: frame-ancestors 'none'` plus `X-Frame-Options: DENY`. The temporary gateway, browser session, and config directory were cleaned.
- `conda run -n llm-rosetta make build`: passed; wheel and sdist built from the current checkout.
- `conda run -n llm-rosetta make check-codex-compat`: passed against Codex source commit `2e8c3756f95789c215d9ea9a5ade6ec377934b3f`; no compatibility group was classified Changed, while 12 remain Possibly unchanged and retain their documented real-API obligations.
- `conda run -n llm-rosetta make check-release-version RELEASE_TAG=v0.144.0.r0`: passed.
- Isolated Compose smoke built from the current wheel, served `/health` and `/admin` with HTTP 200 on `127.0.0.1:18765`, and preserved the anti-framing headers. `docker run --rm --entrypoint codex-rosetta-gateway codex-rosetta-gateway-local:dev --version` reported `0.144.0.r0`, proving the container content independently of its temporary `dev` tag. The Compose project and temporary config were removed without touching the user's existing gateway on port 8765.
- `git diff --check`: passed before repair and after the final ledger update. `codegraph sync` completed successfully (`Synced 7 changed files`), and the final repository reality check confirmed no staged diff, no `.agent-work/audit/CURRENT.md`, no browser/Compose temp artifacts, and no remaining audit Compose container.
- Not run: credentialed external provider/agentabi matrix, external GitHub Actions, vulnerability/license scans, production load/capacity, backup/restore exercise, and real release/deploy/rollback.

## Simplification and stale-state pass

- F-01 was repaired through the existing DOM/text rendering boundary without a new framework, dependency, server-side schema, or parallel state owner.
- The prior round's clean conclusion is stale with respect to this newly traced Admin source-to-sink path, but its state/persistence and full-gate evidence is not contradicted.
- No second Admin frontend, duplicate state owner, broad fallback, or new dependency is recommended.

## Final result

**No open findings remain from round 15.** F-01 is resolved in the current diff and verified by source-level assertions, a real malicious-value Chromium regression, live Admin smoke, the full 2,723-test collection, package/compatibility/release gates, and isolated Compose smoke. The Draft audit-profile governance decisions and external provider/operations exercises remain explicit audit limitations, not newly confirmed code defects.
