# web.run Stored Reference Debug
Date: 2026-07-13
Codex version: 0.144.0

Historical compatibility evidence; use the maintained ledger and reports for
current conclusions.

## Root cause

The local Search API bridge returned Tavily URLs without assigning Codex-style
`turnXsearchY` references. It also rejected pointer-based `open`, so Codex could
only recover by copying a direct URL.

## Implemented boundary

- Added an app-owned, in-memory reference store scoped by authenticated
  principal plus `SearchRequest.id`.
- Assigned stable `turnXsearchY` references to HTTP/HTTPS Tavily results.
- Reused references for identical request retries and serialized allocation
  under concurrent calls.
- Resolved pointer-based `open` before reusing the existing bounded public-page
  fetcher; unknown and cross-session references fail closed.
- Bounded state by TTL, session count, references per session, batches per
  session, and bounded stored result fields.
- Cleared the store with the owning gateway app lifecycle.

## Verification

- Focused gateway tests: `78 passed`.
- Full suite with loopback socket permission: `3108 passed, 5 skipped`.
- Ruff check, Ruff format check, and ty check passed.
- `make lint` reaches the pre-existing complexity ratchet failure in
  `gateway/tool_profiles.py`; the snapshot was not expanded to hide it.
- `make check-codex-compat` reports that the local Codex source checkout moved
  from the recorded commit and removed `REALTIME_CALLS_ENDPOINT`; this is an
  existing compatibility-baseline mismatch outside this fix.

## Real Codex evidence

Original network-search scenario:

- Run root: `tmp/agent_testing_workspace/202607131357`
- Thread: `019f5d0d-660a-72a2-8388-94c6656524b9`
- Codex alias/provider: `gpt-5.6-sol`, `OpenAI`
- Upstream model: `deepseek-v4-flash`
- Result: `RESULT:NETWORK_SEARCH_OK`
- Gateway Logs: `/Volumes/RAMDisk/202607131357/rosetta-trace.jsonl`
- First search created five references; a repeated identical search reused the
  cached result and the same references.

Supplemental reference-open scenario:

- Run root: `tmp/agent_testing_workspace/202607131358`
- Thread: `019f5d10-8151-7cb1-a3c8-223202906c08`
- Result: `RESULT:NETWORK_OPEN_OK`
- Gateway Logs: `/Volumes/RAMDisk/202607131358/rosetta-trace.jsonl`
- The upstream target requests used `deepseek-v4-flash`.
- The successful model call was
  `exec -> tools.web__run(open: [{ref_id: "turn0search0"}])`.
- The Search API trace recorded `command_types=["open"]` and
  `stored_reference_open_count=1`; the returned page was
  `https://docs.python.org/3/`.
- No shell command, browser automation, or direct-URL open fallback was used.
- Before the successful call, DeepSeek emitted two unsupported direct function
  names. Codex rejected them and the model recovered through the exposed
  `exec` surface; this is a model tool-selection deviation, not a Rosetta
  reference-resolution failure.
