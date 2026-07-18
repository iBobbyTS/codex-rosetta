# Collaboration Namespace restoration and inter-agent payload
Date: 2026-07-12
Codex version: 0.144.0

Historical compatibility evidence; use the maintained ledger and reports for
current conclusions.

## Root causes

- Responses Namespace children were flattened to Chat names, but the restore
  map accepted only the exact flattened form. Third-party models can emit
  compatible underscore, dotted, or unqualified child names.
- DeepSeek rejects dotted Function names, so the canonical model-facing name
  must remain regex-safe.
- Codex `agent_message` carries the real `fork_turns="none"` child task in an
  `encrypted_content` part. Responses→Chat previously ignored the whole item,
  leaving the child's visible `Payload:` empty and causing recursive parent-task
  reconstruction.

## Verified fix

- Canonical expansion is `namespace-function`.
- Return conversion accepts `namespace-function`, `namespace_function`,
  `namespace.function`, and a bare child only when it uniquely identifies one
  Namespace and does not collide with a top-level Function. All collision cases
  remain flat and fail closed.
- `agent_message` becomes a Chat user message and exposes its own encrypted
  payload. Ordinary message/reasoning encrypted content remains opaque.
- Chat descriptions clarify `spawn_agent`, future-only `wait_agent`, canonical
  `list_agents` prefixes, and canonical `send_message` targets.

## Evidence

- Focused converter/gateway suite: `286 passed`.
- Full suite: `3083 passed, 5 skipped`.
- `make lint`: passed.
- DeepSeek/OpenAI identity live runs expose `collaboration-*` and restore native
  `namespace="collaboration"` calls.
- Post-repair `spawn_agent`, `list_agents`, `send_message`, `followup_task`, and
  `interrupt_agent` core scenarios succeeded.
- `wait_agent` still fails when the child's completion notification has already
  entered the current parent input. The native call and arguments are correct;
  Codex waits only for a future mailbox update and does not replay the consumed
  notification. Repeated post-guidance failures confirm a test-timing limitation,
  not a remaining Rosetta mapping defect.

Detailed rounds are recorded in
`docs/dev/version-compatibility/reports/scoped-reference-review.md` and each run's
`artifacts/evaluation.json`.
