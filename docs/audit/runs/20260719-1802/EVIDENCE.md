# Evidence — Omission audit

## Independent subagent findings

- The shared `require_live_call_approval()` gate is present in the two `tests/live_agent` runners and `scripts/run_gateway_integration.sh`, but not in the opt-in `tests/integration/*_e2e.py`, `tests/integration/test_gateway_agentabi.py`, `tests/integration/gpt_relay/run.py` / `capture_proxy.py`, or the `scripts/rosetta-test-{claude-code,opencode,kilo}.sh` agent launch paths.
- `src/codex_rosetta/gateway/admin/routes/config.py:376-387` strips `provider`, `shim`, and `type` before returning provider config to the Admin UI.
- `src/codex_rosetta/gateway/admin/admin.html:2463-2474` still branches on `provider.provider` when choosing a default Responses tool profile. The stripped field is therefore absent for API-loaded providers.
- `src/codex_rosetta/gateway/config.py` still has a known-name fallback when `api_type` is absent; examples contain provider entries without explicit `api_type`. This can make provider name act as a second protocol selector.
- `docs/audit/COVERAGE.md` still marks `CTRL-06` as `Unknown / gap` and retains old P0 queue entries for AUD-001/AUD-002/AUD-003 while the top-level status and remediation report say these are closed.
- Provider transport validation accepts HTTP(S) custom URLs; with the current allow-custom decision, the configured API key can be sent to any such URL unless the owner adds a host/network boundary.

## Local corroboration

- `rg -n "require_live_call_approval|API_KEY|agentabi|gpt_relay|capture_proxy" tests/integration tests/live_agent scripts` confirms direct credential/client/process entry points outside the shared gate.
- `nl -ba` inspection confirms the Admin/UI and config line references above.
- No real upstream call or credential value was accessed by this audit.

## Validation boundary

This run is static/deterministic only. It does not establish provider quality, egress behavior, deployment security, browser behavior, restore capability, or availability.
