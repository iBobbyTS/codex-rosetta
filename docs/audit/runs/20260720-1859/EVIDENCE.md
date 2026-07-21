# Audit Run Evidence

Run: `20260720-1859`
Repository head/environment: `6d1bc7affdb02c3c928c84ee49b321011363aea4`; macOS, Python 3.14.6 via `llm-rosetta`; no real API calls

## Evidence Index

| Unit | Status | Severity | Coverage IDs | Finding IDs | Evidence summary | Gaps |
| --- | --- | --- | --- | --- | --- | --- |
| UNIT-001 | Reviewed and remediated | Must Fix / Closed | PROVIDER-01, SIDE-01, SCN-03, SCN-04, CTRL-03 | AUD-017 | discovery proved accepted credential `data` rewrote mandatory SSE framing; remediation now preserves safe output and fails closed before colliding content is released | no live upstream; encoded/covert reflection outside exact-match claim |
| UNIT-002 | Reviewed and remediated | Should Plan / Closed | AUTH-02, SCN-08, SCN-09 | AUD-018 | discovery proved root-list JSON escaped via `AttributeError`; remediation validates provider-specific schemas and returns one controlled error | no browser/LAN deployment or real provider pagination |

---

## UNIT-001 — Exact credential replacement can corrupt provider protocols

- Scope reason: changed/high-churn, invalidated, finding follow-up
- Status: Reviewed
- Outcome: Must Fix
- Coverage IDs: PROVIDER-01, SIDE-01, SCN-03, SCN-04, CTRL-03
- Finding IDs: AUD-017

### Scope and boundaries

- Components/files/interfaces/workflows: `GatewayConfig`, `KeyRing`, `SecretRedactor`, `StreamingSecretRedactor`, `CredentialRedactingTransport`, raw Responses SSE
- Quality attributes: correctness, security, interoperability, operability
- Scenarios/controls: configured provider credential, passthrough raw SSE, exact reflected-value removal
- Excluded sub-scope: real providers, encoded/covert reflection, implementation alternatives

### Hypotheses and disposition

| Candidate | Evidence sought | Disposition | Evidence/reason |
| --- | --- | --- | --- |
| Only actual reflected secrets are changed | compare accepted credential domain with protocol bytes | Confirmed defect | credentials are arbitrary non-empty strings; `data` is both accepted credential and mandatory SSE field name |
| Existing split tests prove non-secret preservation | inspect oracle and token corpus | Rejected | tests use long unique tokens and define expected output as unconditional byte replacement |
| Corruption is limited to raw SSE | inspect parsed-object exact replacement | Rejected | `_redact_exact` also rewrites string keys and values; short/common credentials can alter JSON schema and semantic values |

### Evidence inspected

- Code/configuration:
  - `gateway/transport/provider_info.py:35-50,87,94-103` accepts every non-empty comma-separated segment as a selectable wire credential.
  - `observability/redaction.py:69-89,153-172,175-229` registers each credential as an unconstrained substring and replaces matches in strings, bytes, dictionary keys, and arbitrary stream positions.
  - `gateway/transport/credential_redaction.py:90-126,237-247` applies the replacement to parsed events, raw SSE chunks, and non-streaming raw bodies.
- Tests/scanners:
  - `tests/gateway/test_transport_credential_redaction.py:243-263` uses `raw-stream-secret` and an unconditional `payload.replace(token, b"[REDACTED]")` oracle; it does not sample tokens overlapping SSE or JSON syntax.
- Runtime/logs/metrics/traces: deterministic in-process probe only.
- Build/release/provenance: not applicable.
- Docs/profile/ADR/history: approved profile simultaneously requires configured-token removal and preservation of Codex protocol correctness; no supported credential-length contract exists.
- Human/operator evidence: post-run owner decision recorded below; no minimum credential length, mandatory Gateway API-key access, and controlled fail-closed collision handling.

### Commands and results

| Command/check | Result | Environment/head | Limitation |
| --- | --- | --- | --- |
| Construct real `GatewayConfig` with custom Responses provider `api_key="data"`, pass standard SSE bytes through `SecretRedactor(provider.credential_values).redact_wire_bytes()` | output begins `event: ...\n[REDACTED]: ...`; `framing_preserved=False` | `6d1bc7a`, Python 3.14.6 | deterministic local probe, no socket/provider |
| Same direct redactor probe with `a`, `id`, `data`, `test` | `a` rewrites event/payload text, `id` rewrites JSON key, `data` rewrites SSE field; `test` does not collide in sample | same | illustrative corpus, not exhaustive |
| `pytest -q tests/gateway/test_transport_credential_redaction.py tests/gateway/test_provider_return_redaction.py tests/gateway/test_admin_model_discovery_cleanup.py` | `22 passed` | same | current tests do not assert safe behavior for colliding credentials |

### Scenario result

```text
Stimulus: operator configures a valid custom/local provider credential equal to "data"
Environment: supported local/LAN Gateway, Responses passthrough stream
Expected response/measure: configured credential is not returned and SSE framing/order/non-secret content remain compatible
Observed/supported response: exact byte replacement changes the required SSE field name `data:` to `[REDACTED]:`
Result: Not Satisfied
```

### Findings or No Action rationale

- AUD-017 opened. This is a current reachable protocol-corruption path, not merely a missing test.
- A repair direction cannot be frozen without owner semantics because identical bytes cannot be classified as secret reflection versus legitimate content from output alone.

### Gaps and assumptions

- No claim is made about the credential rules of every external provider; custom/local endpoints are sufficient because the current product accepts them.
- No real provider call was needed to prove the deterministic transform.
- Encoded, hashed, or covert malicious-provider exfiltration remains outside exact-value redaction and must not be implied solved by AUD-017.

### Coverage update

- Previous status: PROVIDER-01/SCN-03/CTRL-03 Fresh (deterministic); SCN-04 Fresh (deterministic)
- New status: Invalidated pending AUD-017 decision/remediation
- Evidence refs: this UNIT-001; AUD-017
- Dependencies/invalidation triggers: credential syntax/validation, exact redactor semantics, parsed/raw transport boundary, SSE formatting
- Next rotation reason: owner decision followed by targeted regression across all credential-bearing clients

---

## UNIT-002 — Admin model discovery does not validate upstream JSON shape

- Scope reason: rotating trust-boundary follow-up
- Status: Reviewed
- Outcome: Should Plan
- Coverage IDs: AUTH-02, SCN-08, SCN-09
- Finding IDs: AUD-018

### Scope and boundaries

- Components/files/interfaces/workflows: Admin `fetch_upstream_models`, bounded HTTP response, credential redaction, OpenAI/Anthropic/Google model-list normalization
- Quality attributes: reliability, security, operability
- Scenarios/controls: Admin-triggered request to untrusted configured provider
- Excluded sub-scope: browser rendering, live provider behavior, provider-specific pagination

### Hypotheses and disposition

| Candidate | Evidence sought | Disposition | Evidence/reason |
| --- | --- | --- | --- |
| JSON parsing is sufficient boundary validation | send syntactically valid wrong root type | Confirmed defect | a root list passes `resp.json()` then crashes at `body.get()` |
| List members are validated before `.get()` | inspect normalization loops | Confirmed defect | every `models`/`data` item is assumed to be a mapping |
| Route returns a stable Admin error | invoke handler with fake bounded response | Rejected | handler raises `AttributeError` instead of returning `JSONResponse` |

### Evidence inspected

- Code/configuration: `gateway/admin/routes/config.py:975-1004` catches only JSON parsing failure, then assumes an object root, list-valued collection, mapping members, string IDs, and sortable homogeneous results.
- Tests/scanners: model-discovery tests cover success, connection failure, invalid JSON, cancellation, redirects, and credential reflection, but not valid JSON with the wrong schema.
- Runtime/logs/metrics/traces: in-process fake HTTP response.
- Build/release/provenance: not applicable.
- Docs/profile/ADR/history: provider output is explicitly untrusted and Admin operations are an always-on critical surface.
- Human/operator evidence: none required.

### Commands and results

| Command/check | Result | Environment/head | Limitation |
| --- | --- | --- | --- |
| Monkeypatch Admin bounded request to return status 200 and `json=lambda: [{"id":"m"}]`; invoke `fetch_upstream_models` | `AttributeError: 'list' object has no attribute 'get'` | `6d1bc7a`, Python 3.14.6 | direct handler probe, not browser/server middleware |
| Related focused pytest set | `22 passed` | same | demonstrates oracle omission, not absence of defect |

### Scenario result

```text
Stimulus: configured upstream returns syntactically valid JSON with a list root
Environment: authenticated Admin requests upstream model discovery
Expected response/measure: reject the malformed provider contract with a stable, non-sensitive Admin error and no partial mutation
Observed/supported response: uncaught AttributeError escapes the route
Result: Not Satisfied
```

### Findings or No Action rationale

- AUD-018 opened. The impact is bounded to the Admin discovery request; no persistent mutation or cross-principal exposure was demonstrated.

### Gaps and assumptions

- Server-level middleware may translate the exception into a generic 500, but that does not satisfy the route's controlled provider-error contract.
- Browser/LAN behavior and real provider payloads were not exercised.

### Coverage update

- Previous status: AUTH-02/SCN-08 Fresh; SCN-09 Fresh (deterministic)
- New status: Partial/Invalidated for upstream model-discovery schema handling
- Evidence refs: this UNIT-002; AUD-018
- Dependencies/invalidation triggers: Admin model-discovery parser, provider model-list schemas, Admin error contract
- Next rotation reason: targeted negative-schema tests and controlled-error verification

## Post-run owner decision — AUD-017

- Authority/date: Project owner / 2026-07-20.
- Configured credentials have no minimum-length requirement.
- Rosetta access always requires a configured Gateway API key; no unauthenticated mode is supported.
- The existing no-credential-leak and protocol-integrity requirements remain in force. If a credential collision cannot be removed while preserving valid SSE/JSON, the implementation must fail closed with a non-sensitive controlled error rather than leak the credential or emit silently corrupted output.
- At decision time this resolved the business decision only. The authorized remediation and phase-separated evidence below supersede that intermediate Open state.

---

## Post-run remediation and phase-separated re-audit

### AUD-017 closure evidence

- `SecretRedactor` now exposes canonical exact collision checks; successful untrusted content is never semantically rewritten.
- Non-stream parsed/raw responses and parsed stream events fail closed on any configured credential collision.
- Raw SSE is gated by complete bounded events. Safe events remain byte-identical across arbitrary chunk splits; no bytes from a colliding event are released; the proxy emits a source-compatible terminal error from a valid event boundary.
- The same controlled collision behavior covers provider transport, every Codex auxiliary endpoint, Tavily, web-run sidecar, Admin discovery, HTTP errors, and detached transport exceptions.
- Regression inputs include one-character, common, numeric, rotated and prefix-overlapping credentials; JSON keys/values; SSE field names, event names, quotes, line endings, and arbitrary splits.
- Deterministic status: `Closed`; PROVIDER-01, SIDE-01, SCN-03, SCN-04, and CTRL-03 restored to `Fresh (deterministic)`.

### AUD-018 closure evidence

- `_normalize_upstream_model_ids` validates an object root, the exact provider collection, object members, and string fallback/shim identifiers before sorting or rendering.
- List/scalar/null roots, missing or wrong collections, non-object members, and non-string identifiers return the same stable non-sensitive model-list error.
- OpenAI-compatible, Anthropic, Google, and custom `model_id_field` success paths retain normalized IDs.
- Deterministic status: `Closed`; AUTH-02, SCN-08, and SCN-09 restored to `Fresh (deterministic)`.

### Verification

| Command/check | Result | Limitation |
| --- | --- | --- |
| focused credential/model-discovery suite | `187 passed` | fake/in-process only |
| full non-integration suite | `3576 passed, 5 skipped, 11 warnings` | no real provider/API calls |
| `make lint` | passed | static checks only |
| `make check-codex-compat` | passed | does not replace a live Codex gate |

No real provider, Codex, Tavily, sidecar, browser, or LAN call was made. Those runtime behaviors remain Unknown rather than inherited from deterministic closure.
