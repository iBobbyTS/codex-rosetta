"""Tests for the Codex source compatibility contract extractor."""

from __future__ import annotations

import json
import re
import runpy
from pathlib import Path

from codex_rosetta.gateway.codex_compaction import COMPACT_PROMPT, SUMMARY_PREFIX
from codex_rosetta.gateway.config import CONFIGURED_RESPONSES_WEB_SEARCH_MODELS

REPO_ROOT = Path(__file__).resolve().parents[1]
BASELINE_PATH = (
    REPO_ROOT / "docs" / "dev" / "version-compatibility" / "codex-source-contract.json"
)
SCRIPT_PATH = REPO_ROOT / "scripts" / "check_codex_compatibility.py"
COMPATIBILITY_POINTS_PATH = (
    REPO_ROOT / "docs" / "dev" / "version-compatibility" / "compatibility-points.md"
)
SCRIPT = runpy.run_path(str(SCRIPT_PATH))

_enum_variants = SCRIPT["_enum_variants"]
_enum_variant_field_contracts = SCRIPT["_enum_variant_field_contracts"]
_find_function = SCRIPT["_find_function"]
_function_call_encrypted_args_contract = SCRIPT[
    "_function_call_encrypted_args_contract"
]
_matching_brace = SCRIPT["_matching_brace"]
_responses_lite_model_fields = SCRIPT["_responses_lite_model_fields"]
_serde_enum_wire_types = SCRIPT["_serde_enum_wire_types"]
_struct_field_contracts = SCRIPT["_struct_field_contracts"]
_struct_fields = SCRIPT["_struct_fields"]
_tool_registration_sites = SCRIPT["_tool_registration_sites"]
compare_snapshots = SCRIPT["compare_snapshots"]
classify_snapshots = SCRIPT["classify_snapshots"]
render_classification = SCRIPT["render_classification"]
snapshot_json = SCRIPT["snapshot_json"]


def test_tool_registration_inventory_uses_current_registry_owners():
    """The reviewed snapshot must follow the 0.147 ToolRegistry assembly path."""
    baseline = json.loads(BASELINE_PATH.read_text(encoding="utf-8"))
    registrations = baseline["contract"]["tool_registration_sites"]

    assert {
        "build_tool_router",
        "add_core_tool_sources",
        "append_dynamic_tool_runtimes",
        "append_extension_tool_executors",
        "append_mcp_tools",
        "apply_direct_model_only_namespace_overrides",
        "collab_tools_enabled",
        "image_generation_available",
        "is_excluded_from_code_mode",
        "is_hidden_by_code_mode_only",
        "multi_agent_v2_enabled",
        "namespace_tools_enabled",
        "search_tool_enabled",
        "spec_for_model_request",
        "merge_into_namespaces",
        "standalone_web_search_enabled",
        "register_code_mode_executors",
        "finalize_tool_router",
    }.issubset(registrations)
    assert {
        "add_dynamic_tools",
        "add_extension_tools",
        "add_tool_sources",
        "prepend_code_mode_executors",
    }.isdisjoint(registrations)

    encrypted_args = baseline["contract"]["function_call_encrypted_args"]
    assert encrypted_args["function_call_fields"]["encrypted_function_args"] == {
        "attributes": [
            '#[serde(default, skip_serializing_if = "Option::is_none")]',
            "#[ts(optional)]",
        ],
        "type": "Option<Vec<String>>",
    }


def _mutate_function_body(source: str, function_name: str) -> str:
    declaration_index = _find_function(source, function_name)
    open_index = source.find("{", declaration_index)
    assert open_index >= 0
    close_index = _matching_brace(source, open_index)
    return (
        source[: open_index + 1]
        + '\npanic!("source-contract mutation")\n'
        + source[close_index:]
    )


def _replace_function_body(source: str, function_name: str, body: str) -> str:
    declaration_index = _find_function(source, function_name)
    open_index = source.find("{", declaration_index)
    assert open_index >= 0
    close_index = _matching_brace(source, open_index)
    return source[: open_index + 1] + f"\n{body}\n" + source[close_index:]


def _mutate_inter_agent_communication_method(source: str, method_name: str) -> str:
    impl_match = re.search(r"\bimpl\s+InterAgentCommunication\s*\{", source)
    assert impl_match is not None
    impl_open = source.find("{", impl_match.start())
    impl_close = _matching_brace(source, impl_open)
    impl_body = source[impl_open + 1 : impl_close]
    mutated_body = _mutate_function_body(impl_body, method_name)
    return source[: impl_open + 1] + mutated_body + source[impl_close:]


def _cp26_source_texts(source_root: Path) -> dict[str, str]:
    paths = {
        "models": "codex-rs/protocol/src/models.rs",
        "router": "codex-rs/core/src/tools/router.rs",
        "client": "codex-rs/core/src/client.rs",
        "protocol": "codex-rs/protocol/src/protocol.rs",
        "multi_agents_v2": "codex-rs/core/src/tools/handlers/multi_agents_v2.rs",
        "agent_communication": "codex-rs/core/src/agent_communication.rs",
        "inter_agent_message": "codex-rs/core/src/context/inter_agent_message.rs",
    }
    return {
        name: (source_root / relative_path).read_text(encoding="utf-8")
        for name, relative_path in paths.items()
    }


def test_cp26_snapshot_changes_for_each_field_and_semantic_owner():
    """Every CP-26 field/dispatch/log/filter owner must affect its snapshot group."""
    source_root = REPO_ROOT.parent / "openai-codex-src"
    sources = _cp26_source_texts(source_root)
    baseline = _function_call_encrypted_args_contract(**sources)

    mutated_models = sources["models"].replace(
        "encrypted_function_args: Option<Vec<String>>",
        "encrypted_function_args: Vec<String>",
        1,
    )
    assert mutated_models != sources["models"]
    assert (
        _function_call_encrypted_args_contract(**{**sources, "models": mutated_models})
        != baseline
    )

    for owner in ("build_tool_call", "direct_source", "tool_log_payload"):
        mutated_router = _mutate_function_body(sources["router"], owner)
        assert (
            _function_call_encrypted_args_contract(
                **{**sources, "router": mutated_router}
            )
            != baseline
        )

    mutated_client = _mutate_function_body(sources["client"], "build_responses_request")
    assert (
        _function_call_encrypted_args_contract(**{**sources, "client": mutated_client})
        != baseline
    )

    for source_name, owner in (
        ("multi_agents_v2", "communication_from_tool_message"),
        ("agent_communication", "emit_agent_communication_send"),
    ):
        mutated = _mutate_function_body(sources[source_name], owner)
        assert (
            _function_call_encrypted_args_contract(**{**sources, source_name: mutated})
            != baseline
        )

    mutated_protocol = sources["protocol"].replace(
        "pub encrypted_content: Option<String>",
        "pub encrypted_content: String",
        1,
    )
    assert mutated_protocol != sources["protocol"]
    assert (
        _function_call_encrypted_args_contract(
            **{**sources, "protocol": mutated_protocol}
        )
        != baseline
    )
    for owner in ("new", "new_encrypted"):
        mutated_protocol = _mutate_inter_agent_communication_method(
            sources["protocol"], owner
        )
        assert (
            _function_call_encrypted_args_contract(
                **{**sources, "protocol": mutated_protocol}
            )
            != baseline
        )

    mutated_message = sources["inter_agent_message"].replace(
        "payload: String", "payload: Vec<u8>", 1
    )
    assert mutated_message != sources["inter_agent_message"]
    assert (
        _function_call_encrypted_args_contract(
            **{**sources, "inter_agent_message": mutated_message}
        )
        != baseline
    )
    for owner in ("as_str", "new", "role", "markers", "type_markers", "body"):
        mutated_message = _mutate_function_body(sources["inter_agent_message"], owner)
        assert (
            _function_call_encrypted_args_contract(
                **{**sources, "inter_agent_message": mutated_message}
            )
            != baseline
        )


def test_new_tool_registration_owners_each_change_the_snapshot_group():
    """Transitive MCP and model-visible assembly changes must invalidate the snapshot."""
    source_root = REPO_ROOT.parent / "openai-codex-src"
    spec_plan = (source_root / "codex-rs/core/src/tools/spec_plan.rs").read_text(
        encoding="utf-8"
    )
    mcp_tool_exposure = (
        source_root / "codex-rs/core/src/mcp_tool_exposure.rs"
    ).read_text(encoding="utf-8")
    baseline = _tool_registration_sites(source_root, spec_plan, mcp_tool_exposure)

    for owner in (
        "search_tool_enabled",
        "namespace_tools_enabled",
        "multi_agent_v2_enabled",
        "collab_tools_enabled",
        "image_generation_available",
        "is_hidden_by_code_mode_only",
        "is_excluded_from_code_mode",
        "standalone_web_search_enabled",
    ):
        mutated = _tool_registration_sites(
            source_root,
            _replace_function_body(spec_plan, owner, "false"),
            mcp_tool_exposure,
        )
        assert mutated != baseline
        assert mutated[owner] != baseline[owner]

    for owner in (
        "apply_direct_model_only_namespace_overrides",
        "spec_for_model_request",
        "merge_into_namespaces",
    ):
        mutated = _tool_registration_sites(
            source_root,
            _mutate_function_body(spec_plan, owner),
            mcp_tool_exposure,
        )
        assert mutated != baseline
        assert mutated[owner] != baseline[owner]

    mcp_owner_mutations = [
        _mutate_function_body(mcp_tool_exposure, "append_mcp_tools"),
        _mutate_function_body(
            mcp_tool_exposure, "filter_non_codex_apps_mcp_tools_only"
        ),
        _mutate_function_body(mcp_tool_exposure, "filter_codex_apps_mcp_tools"),
        mcp_tool_exposure.replace(
            "MAX_AGENT_PLUGIN_MCP_SPEC_BYTES: usize = 8_000",
            "MAX_AGENT_PLUGIN_MCP_SPEC_BYTES: usize = 8_001",
            1,
        ),
        mcp_tool_exposure.replace(
            "MAX_AGENT_PLUGIN_MCP_TOTAL_BYTES: usize = 64_000",
            "MAX_AGENT_PLUGIN_MCP_TOTAL_BYTES: usize = 64_001",
            1,
        ),
    ]
    for mutated_mcp in mcp_owner_mutations:
        assert mutated_mcp != mcp_tool_exposure
        mutated = _tool_registration_sites(source_root, spec_plan, mutated_mcp)
        assert mutated != baseline
        assert mutated["append_mcp_tools"] != baseline["append_mcp_tools"]


def test_compatibility_ledger_has_one_registry_overview_and_matrix_row_per_point():
    """CP-01 through CP-26 must share one canonical name in all three tables."""
    text = COMPATIBILITY_POINTS_PATH.read_text(encoding="utf-8")
    registry_text, remainder = text.split("## Current upgrade status", 1)
    overview_text, remainder = remainder.split("## Compatibility point test matrix", 1)
    matrix_text = remainder.split("## 1. Request, header and session identity", 1)[0]

    registry = re.findall(
        r"^\| `(?P<id>CP-\d{2})` \| (?P<name>[^|]+?) \|$", registry_text, re.MULTILINE
    )
    overview_names = re.findall(
        r"^\| (?P<name>[^|]+?) \|", overview_text, re.MULTILINE
    )[2:]
    matrix_names = re.findall(r"^\| (?P<name>[^|]+?) \|", matrix_text, re.MULTILINE)[2:]

    assert [point_id for point_id, _ in registry] == [
        f"CP-{index:02d}" for index in range(1, 27)
    ]
    canonical_names = [name for _, name in registry]
    assert len(overview_names) == len(canonical_names)
    assert len(matrix_names) == len(canonical_names)
    assert sorted(overview_names) == sorted(canonical_names)
    assert sorted(matrix_names) == sorted(canonical_names)


def test_configured_responses_search_models_match_reviewed_codex_contract():
    """Force an explicit search-routing review when Responses Lite models drift."""
    baseline = json.loads(BASELINE_PATH.read_text(encoding="utf-8"))
    source_models = baseline["contract"]["responses_lite_model_fields"]

    assert {model["slug"] for model in source_models} == set(
        CONFIGURED_RESPONSES_WEB_SEARCH_MODELS
    )


def test_rust_extractor_ignores_braces_in_comments_and_strings():
    source = r"""
pub struct Demo {
    pub alpha: String,
    /* } nested /* { */ comment */
    pub beta: &'static str,
    #[doc = r##"}"##]
    pub raw: &'static str,
}

pub struct Later {
    pub excluded: bool,
}
"""

    assert _struct_fields(source, "Demo") == ["alpha", "beta", "raw"]


def test_enum_extractors_capture_variants_and_wire_renames():
    source = """
pub enum ResponseItem {
    Message { text: String },
    FunctionCall(String),
    Other,
}

pub enum ToolSpec {
    #[serde(rename = "function")]
    Function(FunctionTool),
    #[serde(rename = "tool_search")]
    ToolSearch(ToolSearchTool),
}
"""

    assert _enum_variants(source, "ResponseItem") == [
        "FunctionCall",
        "Message",
        "Other",
    ]
    assert _serde_enum_wire_types(source, "ToolSpec") == {
        "function": "Function",
        "tool_search": "ToolSearch",
    }


def test_field_contracts_capture_types_and_attributes():
    source = """
pub struct ModelMessages {
    pub instructions_template: Option<String>,
    pub approvals: Option<ApprovalMessages>,
}

pub enum ResponseItem {
    AdditionalTools {
        #[serde(default, skip_serializing_if = "Option::is_none")]
        id: Option<String>,
        role: String,
        tools: Vec<serde_json::Value>,
    },
}
"""

    assert _struct_field_contracts(source, "ModelMessages") == {
        "approvals": {"attributes": [], "type": "Option<ApprovalMessages>"},
        "instructions_template": {"attributes": [], "type": "Option<String>"},
    }
    assert _enum_variant_field_contracts(source, "ResponseItem", "AdditionalTools") == {
        "id": {
            "attributes": [
                '#[serde(default, skip_serializing_if = "Option::is_none")]'
            ],
            "type": "Option<String>",
        },
        "role": {"attributes": [], "type": "String"},
        "tools": {"attributes": [], "type": "Vec<serde_json::Value>"},
    }


def test_responses_lite_snapshot_keeps_stable_capability_subset():
    models_json = json.dumps(
        {
            "models": [
                {
                    "slug": "regular",
                    "use_responses_lite": False,
                },
                {
                    "slug": "lite-z",
                    "tool_mode": "code_mode_only",
                    "multi_agent_version": "v2",
                    "use_responses_lite": True,
                    "input_modalities": ["text", "image"],
                    "supports_parallel_tool_calls": True,
                    "supports_search_tool": True,
                    "supported_reasoning_levels": [
                        {"effort": "medium", "description": "ignored text"},
                        {"effort": "ultra", "description": "also ignored"},
                    ],
                    "default_reasoning_level": "medium",
                    "default_reasoning_summary": "none",
                    "web_search_tool_type": "text_and_image",
                    "apply_patch_tool_type": "freeform",
                    "base_instructions": "volatile and intentionally omitted",
                },
                {
                    "slug": "lite-a",
                    "tool_mode": "direct",
                    "multi_agent_version": "v1",
                    "use_responses_lite": True,
                    "input_modalities": ["text"],
                    "supports_parallel_tool_calls": False,
                    "supports_search_tool": False,
                    "supported_reasoning_levels": [{"effort": "low"}],
                    "default_reasoning_level": "low",
                    "default_reasoning_summary": "none",
                    "web_search_tool_type": "text",
                    "apply_patch_tool_type": None,
                },
            ]
        }
    )

    snapshot = _responses_lite_model_fields(models_json)

    assert [model["slug"] for model in snapshot] == ["lite-a", "lite-z"]
    assert snapshot[1]["supported_reasoning_levels"] == ["medium", "ultra"]
    assert snapshot[1]["tool_mode"] == "code_mode_only"
    assert snapshot[1]["multi_agent_version"] == "v2"
    assert "base_instructions" not in snapshot[1]


def test_snapshot_comparison_can_separate_contract_drift_from_commit_change():
    baseline = {
        "schema_version": 1,
        "codex_source_commit": "old",
        "contract": {"message_phase_variants": ["Commentary", "FinalAnswer"]},
    }
    commit_only = {**baseline, "codex_source_commit": "new"}
    contract_change = {
        **commit_only,
        "contract": {
            "message_phase_variants": ["Commentary", "FinalAnswer", "Progress"]
        },
    }

    assert compare_snapshots(baseline, commit_only)
    assert compare_snapshots(baseline, commit_only, check_source_commit=False) == ""
    assert compare_snapshots(baseline, contract_change, check_source_commit=False)


def test_checked_in_baseline_uses_canonical_serialization():
    baseline_text = BASELINE_PATH.read_text(encoding="utf-8")
    baseline = json.loads(baseline_text)

    assert baseline_text == snapshot_json(baseline)
    assert baseline["schema_version"] == 3
    assert baseline["codex_source_commit"]


def test_bundled_remote_compaction_prompts_match_the_reviewed_codex_source():
    source_root = REPO_ROOT.parent / "openai-codex-src"
    assert COMPACT_PROMPT == (
        source_root / "codex-rs/prompts/templates/compact/prompt.md"
    ).read_text(encoding="utf-8")
    assert SUMMARY_PREFIX == (
        source_root / "codex-rs/prompts/templates/compact/summary_prefix.md"
    ).read_text(encoding="utf-8")


def test_snapshot_classification_always_uses_three_result_categories():
    baseline = {
        "schema_version": 1,
        "codex_source_commit": "same",
        "contract": {
            "endpoints": {"RESPONSES_ENDPOINT": "/responses"},
            "model_info_fields": ["slug", "tool_mode"],
        },
    }

    classification = classify_snapshots(baseline, baseline)
    rendered = render_classification(classification)

    assert any(
        "codex_source_commit" in item
        for item in classification["high_confidence_unchanged"]
    )
    assert any(
        "contract.endpoints" in item
        for item in classification["high_confidence_unchanged"]
    )
    assert any(
        "contract.model_info_fields" in item
        for item in classification["high_confidence_unchanged"]
    )
    assert classification["changed"] == []
    assert "High-confidence unchanged:" in rendered
    assert "Possibly unchanged:" in rendered
    assert "Changed:\n  - None" in rendered


def test_new_complete_value_contracts_are_high_confidence():
    complete_value_contracts = {
        "approval_messages_fields": {"on_request": {"type": "Option<String>"}},
        "auto_review_messages_fields": {"policy": {"type": "Option<String>"}},
        "model_info_fields": {"slug": {"type": "String"}},
        "model_messages_fields": {"approvals": {"type": "Option<ApprovalMessages>"}},
        "permission_messages_fields": {"read_only": {"type": "Option<String>"}},
        "response_item_id": {"serde_transparent": True},
        "response_item_additional_tools_fields": {
            "tools": {"type": "Vec<serde_json::Value>"}
        },
        "responses_lite_model_fields": [
            {
                "slug": "gpt-test",
                "tool_mode": "code_mode_only",
                "multi_agent_version": "v2",
                "supported_reasoning_levels": ["low", "ultra"],
            }
        ],
        "search_response_fields": {"results": {"type": "Option<Vec<JsonValue>>"}},
        "sse_input_token_details_fields": {"cache_write_tokens": {"type": "i64"}},
        "tool_spec_web_search_fields": {
            "external_web_access": {"type": "Option<bool>"},
            "indexed_web_access": {"type": "Option<bool>"},
        },
    }
    snapshot = {
        "schema_version": 1,
        "codex_source_commit": "same",
        "contract": complete_value_contracts,
    }

    classification = classify_snapshots(snapshot, snapshot)

    classified_paths = "\n".join(classification["high_confidence_unchanged"])
    for key in complete_value_contracts:
        assert f"contract.{key}" in classified_paths
    assert classification["possibly_unchanged"] == []
    assert classification["changed"] == []


def test_snapshot_classification_reports_commit_and_contract_changes():
    baseline = {
        "schema_version": 1,
        "codex_source_commit": "old",
        "contract": {"endpoints": {"RESPONSES_ENDPOINT": "/responses"}},
    }
    current = {
        "schema_version": 1,
        "codex_source_commit": "new",
        "contract": {"endpoints": {"RESPONSES_ENDPOINT": "/v2/responses"}},
    }

    classification = classify_snapshots(baseline, current, check_source_commit=False)

    assert classification["high_confidence_unchanged"] == []
    assert classification["possibly_unchanged"] == []
    assert classification["changed"] == [
        "codex_source_commit: old -> new (ignored; does not affect exit status)",
        "contract.endpoints: extracted value changed (see detailed diff)",
    ]
