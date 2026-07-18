# Codex Compatibility Evidence

This directory contains historical source research, captured runtime
observations, and supporting protocol notes used by the maintained Codex
compatibility ledger.

These files are evidence, not current compatibility claims. The authoritative
current contract, required checks, and version decisions remain in:

- [`../compatibility-points.md`](../compatibility-points.md)
- [`../rosetta-source-map.md`](../rosetta-source-map.md)
- [`../upgrade-checklist.md`](../upgrade-checklist.md)
- [`../reports/`](../reports/README.md)

## Evidence index

### 2026-07-06 — Responses and request contracts

- [`codex_responses_context_observation.md`](codex_responses_context_observation.md): Codex `0.142.5` full-history Responses request observation.
- [`codex_file_editing_toolset_research.md`](codex_file_editing_toolset_research.md): source snapshot of direct and Code Mode file-editing tools.
- [`openai_responses_passthrough_notes.md`](openai_responses_passthrough_notes.md): request, output-item, SSE, phase, and direct-passthrough contract notes.
- [`responses_include_passthrough.md`](responses_include_passthrough.md): preservation of `include` and encrypted reasoning requests.
- [`responses_namespaced_function_calls.md`](responses_namespaced_function_calls.md): Namespace and item-ID restoration for Codex tools.
- [`responses_reasoning_passthrough.md`](responses_reasoning_passthrough.md): reasoning output-item retention through streaming conversion.
- [`responses_tool_search_passthrough.md`](responses_tool_search_passthrough.md): native deferred-tool item preservation and loop continuation.
- [`user_agent_passthrough.md`](user_agent_passthrough.md): client header forwarding evidence.

### 2026-07-07 — tools, streams, phase, and reasoning

- [`chat_stream_eof_finish.md`](chat_stream_eof_finish.md): normal Chat EOF completion fallback.
- [`codex_cli_plan_goal_subagent.md`](codex_cli_plan_goal_subagent.md): Plan/Goal/subagent runner boundaries and live observations.
- [`codex_tool_localization.md`](codex_tool_localization.md): original code-tool localization investigation.
- [`deepseek_reasoning_content_tool_loops.md`](deepseek_reasoning_content_tool_loops.md): third-party reasoning-history continuation.
- [`gateway_mandatory_stream_trace.md`](gateway_mandatory_stream_trace.md): stream evidence ownership and duplicate raw-trace correction.
- [`responses_full_turn_phase_buffer.md`](responses_full_turn_phase_buffer.md): structural commentary/final phase buffering.

### Later evidence

- [`pipeline_profile_rounding_flake.md`](pipeline_profile_rounding_flake.md): test quantization rather than conversion-state leakage.
- [`token_redaction_retention_semantics.md`](token_redaction_retention_semantics.md): supporting diagnostic-redaction, retention, and compatibility-check evidence.
- [`collaboration_bare_child_name.md`](collaboration_bare_child_name.md): Namespace aliases and inter-agent payload delivery.
- [`network_change_stream_stall.md`](network_change_stream_stall.md): bounded failure propagation after network-route changes.
- [`web_run_custom_exec_stream.md`](web_run_custom_exec_stream.md): custom `exec` stream restoration and result replay.
- [`web_run_stored_references.md`](web_run_stored_references.md): scoped `turnXsearchY` allocation and open behavior.
- [`internal_exec_container.md`](internal_exec_container.md): Disabled parent `exec` conversion-container behavior.
- [`real_agent_tool_test_results.md`](real_agent_tool_test_results.md): version-bound real-agent observations formerly duplicated in user docs.
- [`model_group_restart_notice.md`](model_group_restart_notice.md): local-mode catalog/config idempotence.
- [`remote_compaction_persistence.md`](remote_compaction_persistence.md): internal compaction persistence repair evidence.
- [`remote_compaction_live_gaps.md`](remote_compaction_live_gaps.md): unresolved real-provider summary-quality gaps.
- [`deferred_plugin_live_discovery.md`](deferred_plugin_live_discovery.md): deferred plugin/MCP/Skill source and live behavior.
- [`live_agent_failure_reanalysis.md`](live_agent_failure_reanalysis.md): source-backed namespace, image-generation, Skill, and compaction reclassification.
