"""Gateway-only tool adaptation for Codex-facing routes.

The functions in this module localize Codex's native editing tools for
OpenAI-compatible chat upstreams, then translate model-selected localized tools
back to Codex-native tool calls before the response is returned to Codex.
"""

from __future__ import annotations

import base64
import json
import shlex
import uuid
from collections import OrderedDict
from collections.abc import Iterator
from dataclasses import dataclass, replace
from typing import Any

from .code_mode_projection import (
    ALL_TOOLS_READ_CHAT_NAME,
    ALL_TOOLS_SEARCH_CHAT_NAME,
    DEFERRED_EXEC_GUIDANCE,
    DEFERRED_TOOL_DISPATCH_CHAT_NAME,
    NODE_REPL_TOOL_NAMES,
    ExecDescriptionSection,
    ExecToolProjection,
    all_tools_read_definition,
    all_tools_search_definition,
    build_exec_script,
    discovered_all_tools_search_names,
    discovered_deferred_exec_tools,
    deferred_tool_definition_hash,
    exec_tool_section_names,
    exec_tool_projections_for_route,
    plan_exec_tool_definitions,
    prune_exec_tool_description,
)
from .state_scope import GatewayStateScope
from .tool_profiles import route_tool_state, tool_catalog_lookups, tool_profile_contract
from .tool_profiles import catalog_runtime_adapters, catalog_tool_definition


DEFAULT_TOOL_CALL_CACHE_TTL_HOURS = 24.0
DEFAULT_USE_APPLY_PATCH_FOR_CODE_EDITS = True
DEFAULT_ENABLE_PHASE_DETECTION = True
LOCALIZATION_CAPABILITIES_KEY = "_codex_tool_localization_capabilities"
READ_OUTPUT_CACHE_KEY = "_codex_read_output_cache"
EXEC_PROJECTIONS_KEY = "_codex_exec_tool_projections"
DEFERRED_CANDIDATES_KEY = "_codex_deferred_tool_candidates"


def _catalog_names_by_adapter(adapter_id: str) -> frozenset[str]:
    """Return model-facing names owned by one validated runtime adapter."""
    lookup = tool_catalog_lookups()
    return frozenset(
        item["name"]
        for item_id, item in lookup["items"].items()
        if adapter_id in catalog_runtime_adapters(item_id)
    )


def _localized_code_tool_names() -> frozenset[str]:
    return _catalog_names_by_adapter("localized_file_tool")


def _recognized_localized_code_tool_names() -> frozenset[str]:
    catalog = tool_profile_contract()["catalog"]
    return (
        _localized_code_tool_names()
        | _catalog_names_by_adapter("send_line")
        | frozenset(catalog.history_aliases)
    )


def _native_code_tool_names() -> frozenset[str]:
    return frozenset(
        item["name"]
        for item in tool_catalog_lookups()["items"].values()
        if item.get("delivery", {}).get("localized_native_source") is True
    )


@dataclass(frozen=True)
class LocalizedToolMapping:
    """Mapping between a model-facing localized call and a Codex-native call."""

    call_id: str
    localized_name: str
    localized_input: dict[str, Any]
    native_name: str
    native_input: Any
    native_type: str = "function"

    def original_tool_call(self) -> dict[str, Any]:
        """Return the model-facing Chat tool call shape for persistence."""
        return _chat_tool_call(self.call_id, self.localized_name, self.localized_input)

    def codex_tool_call(self) -> dict[str, Any]:
        """Return the Codex-native Chat tool call shape for persistence."""
        call = _chat_tool_call(self.call_id, self.native_name, self.native_input)
        if self.native_type != "function":
            call["_codex_rosetta_native_type"] = self.native_type
        return call


@dataclass(frozen=True)
class ReadCall:
    """Model-facing Read call identity and file path."""

    call_id: str
    file_path: str


class ReadOutputCache:
    """Session-local cache rebuilt from localized Chat history."""

    def __init__(self) -> None:
        self._items: dict[str, list[str]] = {}
        self._pending_reads: dict[str, str] = {}
        self._pending_mutations: dict[str, str] = {}

    def remember_read_call(self, call_id: str, file_path: str) -> None:
        """Remember the file path associated with a Read call."""
        if call_id and file_path:
            self._pending_reads[call_id] = file_path

    def remember_tool_output(self, call_id: str, text: str) -> None:
        """Remember Read outputs and invalidate cache after successful edits."""
        file_path = self._pending_reads.get(call_id)
        if file_path is not None:
            self.remember(file_path, text)
            return
        file_path = self._pending_mutations.get(call_id)
        if file_path is not None and not _tool_output_indicates_failure(text):
            self.invalidate(file_path)

    def remember(self, file_path: str, text: str) -> None:
        """Remember one Read output for a file path."""
        if not file_path:
            return
        self._items.setdefault(file_path, []).append(_unwrap_command_output(text))

    def remember_mutating_call(self, call_id: str, file_path: str) -> None:
        """Remember a localized call that may change one file."""
        if call_id and file_path:
            self._pending_mutations[call_id] = file_path

    def invalidate(self, file_path: str) -> None:
        """Drop cached Read outputs for a file path."""
        self._items.pop(file_path, None)

    def expand_edit(
        self,
        *,
        file_path: str,
        old_string: str,
        new_string: str,
    ) -> tuple[str, str] | None:
        """Expand a substring edit to a full-line replacement when unambiguous."""
        if not file_path or not old_string:
            return None

        candidates: list[tuple[str, str]] = []
        for text in self._items.get(file_path, []):
            candidates.extend(
                _line_expansion_candidates(
                    text,
                    old_string=old_string,
                    new_string=new_string,
                )
            )

        unique: list[tuple[str, str]] = []
        for candidate in candidates:
            if candidate not in unique:
                unique.append(candidate)

        if len(unique) != 1:
            return None
        expanded_old, expanded_new = unique[0]
        if expanded_old == old_string:
            return None
        return expanded_old, expanded_new


def _iter_tool_capability_definitions(tools: list[Any]) -> Iterator[dict[str, Any]]:
    """Yield leaf definitions, descending only through Namespace child lists."""
    for tool in tools:
        if not isinstance(tool, dict):
            continue
        if tool.get("type") != "namespace":
            yield tool
            continue
        children = tool.get("tools")
        if isinstance(children, list):
            yield from _iter_tool_capability_definitions(children)


@dataclass(frozen=True)
class NativeToolCapabilities:
    """Executable Codex tool capabilities present in the original request."""

    has_exec_command: bool = False
    has_shell_command: bool = False
    has_write_stdin: bool = False
    has_custom_apply_patch: bool = True
    has_custom_exec: bool = False

    @classmethod
    def from_chat_tools(cls, tools: Any) -> NativeToolCapabilities:
        """Infer native tool capabilities from converted Chat tool definitions."""
        if not isinstance(tools, list):
            return cls()

        has_exec_command = False
        has_shell_command = False
        has_write_stdin = False
        has_custom_apply_patch = False
        has_custom_exec = False
        for tool in _iter_tool_capability_definitions(tools):
            name = _chat_tool_name(tool)
            if not isinstance(name, str) or not name:
                continue
            tool_type = _chat_tool_type(tool)
            if tool_type == "function" and name == "exec_command":
                has_exec_command = True
            elif tool_type == "function" and name == "shell_command":
                has_shell_command = True
            elif tool_type == "function" and name == "write_stdin":
                has_write_stdin = True
            elif tool_type == "custom" and name == "apply_patch":
                has_custom_apply_patch = True
            elif tool_type == "custom" and name == "exec":
                has_custom_exec = True

        return cls(
            has_exec_command=has_exec_command,
            has_shell_command=has_shell_command,
            has_write_stdin=has_write_stdin,
            has_custom_apply_patch=has_custom_apply_patch,
            has_custom_exec=has_custom_exec,
        )

    def to_metadata(self) -> dict[str, bool]:
        """Serialize capabilities for internal gateway metadata."""
        return {
            "has_exec_command": self.has_exec_command,
            "has_shell_command": self.has_shell_command,
            "has_write_stdin": self.has_write_stdin,
            "has_custom_apply_patch": self.has_custom_apply_patch,
            "has_custom_exec": self.has_custom_exec,
        }

    @classmethod
    def from_metadata(cls, value: Any) -> NativeToolCapabilities:
        """Deserialize capabilities from internal gateway metadata."""
        if not isinstance(value, dict):
            return cls()
        return cls(
            has_exec_command=bool(value.get("has_exec_command")),
            has_shell_command=bool(value.get("has_shell_command")),
            has_write_stdin=bool(value.get("has_write_stdin")),
            has_custom_apply_patch=bool(value.get("has_custom_apply_patch", True)),
            has_custom_exec=bool(value.get("has_custom_exec")),
        )


class CodexToolLocalizationStore:
    """Small in-memory store for localizing prior assistant tool calls.

    Codex sends the conversation history back on later turns.  The gateway
    returns native Codex tool calls downstream, so later Responses->Chat request
    conversion sees native names in assistant history.  This store lets the
    gateway restore the original localized names/arguments for the upstream
    model when it recognizes the call_id.
    """

    def __init__(
        self,
        *,
        max_size: int = 10_000,
        _items: OrderedDict[tuple[GatewayStateScope, str], LocalizedToolMapping]
        | None = None,
        _scope: GatewayStateScope | None = None,
    ) -> None:
        self._is_root = _items is None
        self._items = _items if _items is not None else OrderedDict()
        self._max_size = max_size
        self._scope = _scope or GatewayStateScope(
            principal_id="__standalone_store__",
            provider_name="",
            model="",
            conversation_id=f"request:{uuid.uuid4().hex}",
            persistent=False,
        )

    def scoped(self, scope: GatewayStateScope) -> CodexToolLocalizationStore:
        """Return a view whose keys are namespaced to *scope*."""
        return CodexToolLocalizationStore(
            max_size=self._max_size,
            _items=self._items,
            _scope=scope,
        )

    def _key(self, call_id: str) -> tuple[GatewayStateScope, str]:
        return self._scope, call_id

    def remember(self, mapping: LocalizedToolMapping) -> None:
        """Remember one localized/native call mapping."""
        if not mapping.call_id:
            return
        key = self._key(mapping.call_id)
        self._items[key] = mapping
        self._items.move_to_end(key)
        while len(self._items) > self._max_size:
            self._items.popitem(last=False)

    def get(self, call_id: str) -> LocalizedToolMapping | None:
        """Return a mapping by call_id, if present."""
        key = self._key(call_id)
        mapping = self._items.get(key)
        if mapping is not None:
            self._items.move_to_end(key)
        return mapping

    def clear(self) -> None:
        """Remove remembered mappings owned by this store's scope."""
        keys = [key for key in self._items if key[0] == self._scope]
        for key in keys:
            del self._items[key]

    def clear_all(self) -> None:
        """Remove all mappings owned by this root store."""
        if not self._is_root:
            raise RuntimeError("clear_all() is only available on a root store")
        self._items.clear()

    def __len__(self) -> int:
        if self._is_root:
            return len(self._items)
        return sum(1 for scope, _call_id in self._items if scope == self._scope)


def should_localize_code_tools(route: Any) -> bool:
    """Return whether a Responses request is crossing into Chat."""
    is_bridge = (
        getattr(route, "source_provider", None)
        in ("openai_responses", "open_responses")
        and getattr(route, "target_provider", None) == "openai_chat"
    )
    if not is_bridge:
        return False
    if not getattr(route, "tool_profile", None):
        return True
    lookup = tool_catalog_lookups()["by_type_name"]
    native_modified = any(
        route_tool_state(route, lookup[(tool_type, name)]) == "modified"
        for tool_type, name in (
            ("custom", "apply_patch"),
            ("function", "exec_command"),
            ("function", "write_stdin"),
            ("function", "shell_command"),
        )
    )
    return (
        native_modified
        or bool(injected_local_tool_names(route))
        or bool(exec_tool_projections_for_route(route))
    )


def localized_native_tool_names(route: Any) -> frozenset[str]:
    """Return native code tools selected for Chat localization."""
    if not getattr(route, "tool_profile", None):
        return _native_code_tool_names()
    lookup = tool_catalog_lookups()["by_type_name"]
    exec_projection_ids = set(tool_profile_contract()["exec_projections"])
    return frozenset(
        name
        for item_id, tool_type, name in (
            ("custom.apply_patch", "custom", "apply_patch"),
            ("function.exec_command", "function", "exec_command"),
            ("function.write_stdin", "function", "write_stdin"),
            ("function.shell_command", "function", "shell_command"),
        )
        if item_id not in exec_projection_ids
        if route_tool_state(route, lookup[(tool_type, name)]) == "modified"
    )


def injected_local_tool_names(route: Any) -> frozenset[str]:
    """Return Rosetta-localized tools enabled by the selected profile."""
    if not getattr(route, "tool_profile", None):
        return _localized_code_tool_names()
    lookup = tool_catalog_lookups()
    return frozenset(
        item["name"]
        for item_id, item in lookup["items"].items()
        if item["type"] == "custom_injection"
        and "localized_file_tool" in catalog_runtime_adapters(item_id)
        and route_tool_state(route, item_id, "injected") == "injected"
    )


def use_apply_patch_for_code_edits(tool_adaptation: dict[str, Any] | None) -> bool:
    """Return whether localized code edits should use Codex apply_patch."""
    if not isinstance(tool_adaptation, dict):
        return DEFAULT_USE_APPLY_PATCH_FOR_CODE_EDITS
    return bool(
        tool_adaptation.get(
            "use_apply_patch_for_code_edits",
            DEFAULT_USE_APPLY_PATCH_FOR_CODE_EDITS,
        )
    )


def enable_phase_detection(tool_adaptation: dict[str, Any] | None) -> bool:
    """Return whether Chat→Responses streams should receive phase detection."""
    if not isinstance(tool_adaptation, dict):
        return DEFAULT_ENABLE_PHASE_DETECTION
    return bool(
        tool_adaptation.get(
            "enable_phase_detection",
            DEFAULT_ENABLE_PHASE_DETECTION,
        )
    )


def localize_code_editing_chat_request(
    body: dict[str, Any],
    *,
    store: CodexToolLocalizationStore | None = None,
    mappings: list[LocalizedToolMapping] | None = None,
    used_call_ids: set[str] | None = None,
    capabilities: NativeToolCapabilities | None = None,
    native_tool_names: frozenset[str] | None = None,
    injected_tool_names: frozenset[str] | None = None,
    exec_projections: dict[str, ExecToolProjection] | None = None,
    profile_route: Any | None = None,
    hide_exec_container: bool = False,
) -> dict[str, Any]:
    """Replace Codex-native edit tools with Claude-Code-like Chat tools."""
    if native_tool_names is None:
        native_tool_names = _native_code_tool_names()
    if injected_tool_names is None:
        injected_tool_names = _localized_code_tool_names()
    adapted = dict(body)
    tools = adapted.get("tools")
    removed_native = False
    native_capabilities = capabilities or NativeToolCapabilities.from_chat_tools(tools)
    read_cache = ReadOutputCache()
    messages = adapted.get("messages")
    localized_messages = _localized_history_messages(
        messages,
        store=store,
        mappings=mappings,
        used_call_ids=used_call_ids,
        read_cache=read_cache,
    )
    if localized_messages is not None:
        adapted["messages"] = localized_messages
        adapted[READ_OUTPUT_CACHE_KEY] = read_cache
        messages = localized_messages

    discovered = discovered_deferred_exec_tools(messages)
    discovered_search_names = discovered_all_tools_search_names(messages)
    requested_projections = dict(exec_projections or {})

    if isinstance(tools, list):
        preserved_tools: list[Any] = []
        existing_names: set[str] = set()
        for tool in tools:
            name = _chat_tool_name(tool)
            if name in native_tool_names:
                removed_native = True
                continue
            if name:
                existing_names.add(name)
            preserved_tools.append(tool)

        (
            projected_tools,
            active_projections,
            projection_sections,
            deferred_candidates,
        ) = _project_exec_chat_tools(
            preserved_tools,
            existing_names,
            native_capabilities,
            requested_projections,
            profile_route,
        )
        _configure_deferred_tool_projections(
            projected_tools,
            active_projections,
            discovered.projections,
            discovered.definition_hashes,
            discovered_search_names,
            existing_names,
        )
        localized_tools = [
            tool
            for tool in _catalog_injection_definitions()
            if (
                _chat_tool_name(tool) in injected_tool_names
                or (
                    _chat_tool_name(tool) == "send_line"
                    and native_capabilities.has_write_stdin
                    and (
                        profile_route is None
                        or (
                            route_tool_state(
                                profile_route,
                                "injection.rosetta.send_line",
                                "injected",
                            )
                            == "injected"
                            and route_tool_state(
                                profile_route,
                                "function.write_stdin",
                            )
                            != "disabled"
                        )
                    )
                )
            )
            and _chat_tool_name(tool) not in existing_names
            and _chat_tool_name(tool) not in active_projections
        ]
        emitted_localized_names = {
            name for tool in localized_tools if (name := _chat_tool_name(tool))
        }
        consumed_sections = [
            projection_sections[name]
            for name, projection in active_projections.items()
            if name in projection_sections
            and (
                (projection.model_visible and name in projected_tools)
                or (
                    bool(projection.description_replaced_by)
                    and set(projection.description_replaced_by)
                    <= emitted_localized_names
                )
            )
        ]
        model_tools, removed_projected_containers = (
            _rewrite_or_hide_exec_projection_container(
                preserved_tools,
                projected_tools,
                consumed_sections=consumed_sections,
                hide_when_empty=hide_exec_container,
            )
        )

        if (
            removed_native
            or injected_tool_names
            or active_projections
            or removed_projected_containers
            or _localized_code_tool_names().intersection(existing_names)
        ):
            adapted["tools"] = (
                model_tools
                + localized_tools
                + [
                    projected_tools[name]
                    for name in active_projections
                    if name in projected_tools
                ]
            )
            selected_tool = _tool_choice_name(adapted.get("tool_choice"))
            if selected_tool in native_tool_names | removed_projected_containers:
                adapted["tool_choice"] = "auto"
            adapted[LOCALIZATION_CAPABILITIES_KEY] = native_capabilities.to_metadata()
            if active_projections:
                adapted[EXEC_PROJECTIONS_KEY] = active_projections
            if deferred_candidates:
                adapted[DEFERRED_CANDIDATES_KEY] = {
                    name: {
                        **candidate,
                        "authorized_definition_hash": discovered.definition_hashes.get(
                            name
                        ),
                    }
                    for name, candidate in deferred_candidates.items()
                }

    return adapted


def _localized_history_messages(
    messages: Any,
    *,
    store: CodexToolLocalizationStore | None,
    mappings: list[LocalizedToolMapping] | None,
    used_call_ids: set[str] | None,
    read_cache: ReadOutputCache,
) -> list[Any] | None:
    """Restore model-facing history and collect read/edit context."""
    if not isinstance(messages, list) or (store is None and not mappings):
        return None
    localized_messages: list[Any] = []
    for message in messages:
        localized = _localize_history_message(
            message,
            store,
            mappings,
            used_call_ids=used_call_ids,
        )
        _update_read_output_cache_from_message(localized, read_cache)
        localized_messages.append(localized)
    return localized_messages


def _configure_deferred_tool_projections(
    projected_tools: dict[str, dict[str, Any]],
    active_projections: dict[str, ExecToolProjection],
    discovered_projections: dict[str, ExecToolProjection],
    discovered_definition_hashes: dict[str, str],
    discovered_search_names: tuple[str, ...],
    existing_names: set[str],
) -> None:
    """Bind request-history authorization without changing model-visible tools."""
    search_active = ALL_TOOLS_SEARCH_CHAT_NAME in active_projections
    read_active = ALL_TOOLS_READ_CHAT_NAME in active_projections
    dispatch_active = (
        search_active
        and read_active
        and DEFERRED_TOOL_DISPATCH_CHAT_NAME in active_projections
    )
    blocked_names = tuple(
        name for name in NODE_REPL_TOOL_NAMES if name in existing_names
    ) + tuple(
        sorted(
            name
            for name in existing_names
            if name.startswith("mcp__") and name not in NODE_REPL_TOOL_NAMES
        )
    )

    search_projection = active_projections.get(ALL_TOOLS_SEARCH_CHAT_NAME)
    if search_projection is not None:
        if ALL_TOOLS_SEARCH_CHAT_NAME in projected_tools:
            projected_tools[ALL_TOOLS_SEARCH_CHAT_NAME] = all_tools_search_definition(
                include_tool_read_guidance=read_active
            )

    read_projection = active_projections.get(ALL_TOOLS_READ_CHAT_NAME)
    if read_projection is not None:
        active_projections[ALL_TOOLS_READ_CHAT_NAME] = replace(
            read_projection,
            authorized_names=discovered_search_names,
            include_dispatch_guidance=dispatch_active,
            dispatch_blocked_names=blocked_names,
        )
        if ALL_TOOLS_READ_CHAT_NAME in projected_tools:
            projected_tools[ALL_TOOLS_READ_CHAT_NAME] = all_tools_read_definition(
                include_dispatch_guidance=dispatch_active
            )

    authorized_names = tuple(
        name for name in discovered_projections if name not in existing_names
    )
    dispatch_projection = active_projections.get(DEFERRED_TOOL_DISPATCH_CHAT_NAME)
    if dispatch_projection is not None:
        if not dispatch_active:
            active_projections.pop(DEFERRED_TOOL_DISPATCH_CHAT_NAME, None)
            projected_tools.pop(DEFERRED_TOOL_DISPATCH_CHAT_NAME, None)
        else:
            active_projections[DEFERRED_TOOL_DISPATCH_CHAT_NAME] = replace(
                dispatch_projection,
                authorized_names=authorized_names,
                authorized_definition_hashes=tuple(
                    (name, discovered_definition_hashes[name])
                    for name in authorized_names
                ),
            )


def _rewrite_or_hide_exec_projection_container(
    preserved_tools: list[Any],
    projected_tools: dict[str, dict[str, Any]],
    *,
    consumed_sections: list[ExecDescriptionSection],
    hide_when_empty: bool,
) -> tuple[list[Any], frozenset[str]]:
    """Prune replaced exec sections and retain only unresolved raw capability."""
    exec_index = next(
        (
            index
            for index, tool in enumerate(preserved_tools)
            if _chat_tool_name(tool) == "exec"
        ),
        None,
    )
    if exec_index is None:
        return preserved_tools, frozenset()
    exec_tool = preserved_tools[exec_index]
    function = exec_tool.get("function") if isinstance(exec_tool, dict) else None
    description = function.get("description") if isinstance(function, dict) else None
    if (
        not isinstance(exec_tool, dict)
        or not isinstance(function, dict)
        or not isinstance(description, str)
    ):
        if not projected_tools and not hide_when_empty:
            return preserved_tools, frozenset()
        return (
            [tool for index, tool in enumerate(preserved_tools) if index != exec_index],
            frozenset({"exec"}),
        )

    pruned_description = prune_exec_tool_description(description, consumed_sections)
    has_deferred_tools = DEFERRED_EXEC_GUIDANCE in pruned_description
    has_unconsumed_sections = bool(exec_tool_section_names(pruned_description))
    source_section_names = exec_tool_section_names(description)
    has_unparsed_source_description = (
        bool(description.strip()) and not source_section_names
    )
    if (
        has_deferred_tools
        or has_unconsumed_sections
        or has_unparsed_source_description
        or (not projected_tools and not hide_when_empty and not consumed_sections)
    ):
        if pruned_description == description:
            return preserved_tools, frozenset()
        rewritten_function = function.copy()
        rewritten_function["description"] = pruned_description
        rewritten_tool = exec_tool.copy()
        rewritten_tool["function"] = rewritten_function
        rewritten_tools = list(preserved_tools)
        rewritten_tools[exec_index] = rewritten_tool
        return rewritten_tools, frozenset()

    return (
        [tool for index, tool in enumerate(preserved_tools) if index != exec_index],
        frozenset({"exec"}),
    )


def _project_exec_chat_tools(
    preserved_tools: list[Any],
    existing_names: set[str],
    capabilities: NativeToolCapabilities,
    projections: dict[str, ExecToolProjection],
    profile_route: Any | None,
) -> tuple[
    dict[str, dict[str, Any]],
    dict[str, ExecToolProjection],
    dict[str, ExecDescriptionSection],
    dict[str, dict[str, Any]],
]:
    """Project parseable nested exec tools that do not conflict with direct tools."""
    if not capabilities.has_custom_exec or not projections:
        return {}, {}, {}, {}
    exec_tool = next(
        (tool for tool in preserved_tools if _chat_tool_name(tool) == "exec"), None
    )
    if not isinstance(exec_tool, dict):
        return {}, {}, {}, {}
    function = exec_tool.get("function")
    if not isinstance(function, dict):
        return {}, {}, {}, {}
    description = function.get("description")
    if not isinstance(description, str):
        return {}, {}, {}, {}
    plan = plan_exec_tool_definitions(
        description,
        projections,
        profile_route=profile_route,
    )
    definitions = plan.definitions
    active = {
        name: projections[name]
        for name in definitions
        if name in projections
        if name not in existing_names
    }
    visible_definitions = {
        name: definition
        for name, definition in definitions.items()
        if name in active and projections[name].model_visible
    }
    active_sections = {
        name: section for name, section in plan.sections.items() if name in active
    }
    deferred_candidates = {
        name: {
            "projection": projections[name],
            "definition": definitions[name],
            "definition_hash": deferred_tool_definition_hash(
                name,
                plan.sections[name].body,
            ),
        }
        for name in definitions
        if name in projections
        and name in existing_names
        and name in plan.sections
        and projections[name].input_mode in {"args", "freeform"}
    }
    return visible_definitions, active, active_sections, deferred_candidates


def restore_localized_history_from_mappings(
    body: dict[str, Any],
    mappings: list[LocalizedToolMapping],
) -> tuple[dict[str, Any], set[str]]:
    """Restore localized history calls from persisted mappings.

    Returns the adapted body and the set of mapping call IDs that were used.
    """
    adapted = dict(body)
    messages = adapted.get("messages")
    if not isinstance(messages, list) or not mappings:
        return adapted, set()

    used_call_ids: set[str] = set()
    adapted["messages"] = [
        _localize_history_message(
            message,
            None,
            mappings,
            used_call_ids=used_call_ids,
        )
        for message in messages
    ]
    return adapted, used_call_ids


def translate_localized_ir_response(
    ir_response: dict[str, Any],
    *,
    store: CodexToolLocalizationStore | None = None,
    on_mapping: Any | None = None,
    capabilities: NativeToolCapabilities | None = None,
    read_cache: ReadOutputCache | None = None,
    use_apply_patch: bool = DEFAULT_USE_APPLY_PATCH_FOR_CODE_EDITS,
    exec_projections: dict[str, ExecToolProjection] | None = None,
) -> dict[str, Any]:
    """Translate localized IR tool calls in-place inside an IR response."""
    for choice in ir_response.get("choices", []):
        if not isinstance(choice, dict):
            continue
        message = choice.get("message")
        if not isinstance(message, dict):
            continue
        content = message.get("content")
        if not isinstance(content, list):
            continue
        for part in content:
            if not isinstance(part, dict) or part.get("type") != "tool_call":
                continue
            translated = translate_localized_tool_call_part(
                part,
                capabilities=capabilities,
                read_cache=read_cache,
                use_apply_patch=use_apply_patch,
                exec_projections=exec_projections,
            )
            if translated is None:
                continue
            part.clear()
            part.update(translated.part)
            if store is not None:
                store.remember(translated.mapping)
            if on_mapping is not None:
                on_mapping(translated.mapping)
    return ir_response


@dataclass(frozen=True)
class TranslatedToolCall:
    """Translated Codex-native IR tool call plus reversible mapping metadata."""

    part: dict[str, Any]
    mapping: LocalizedToolMapping


def translate_localized_tool_call_part(
    part: dict[str, Any],
    *,
    capabilities: NativeToolCapabilities | None = None,
    read_cache: ReadOutputCache | None = None,
    use_apply_patch: bool = DEFAULT_USE_APPLY_PATCH_FOR_CODE_EDITS,
    exec_projections: dict[str, ExecToolProjection] | None = None,
) -> TranslatedToolCall | None:
    """Translate one localized IR tool_call part to a Codex-native tool call."""
    localized_name = part.get("tool_name", "")
    projection = (exec_projections or {}).get(localized_name)
    if (
        localized_name not in _recognized_localized_code_tool_names()
        and projection is None
    ):
        return None

    call_id = part.get("tool_call_id", "")
    localized_input = _ensure_input_dict(part.get("tool_input"))
    if localized_input is None:
        if projection is not None:
            return _exec_error_translation(
                call_id,
                localized_name,
                {},
                f"{localized_name} arguments must be a JSON object.",
            )
        return _error_translation(
            call_id,
            localized_name,
            {},
            f"{localized_name} arguments must be a JSON object.",
        )

    try:
        native_name, native_input, native_type = _translate_localized_call(
            localized_name,
            localized_input,
            projection=projection,
            capabilities=capabilities,
            read_cache=read_cache,
            use_apply_patch=use_apply_patch,
            exec_projections=exec_projections,
        )
    except ValueError as exc:
        if projection is not None:
            return _exec_error_translation(
                call_id, localized_name, localized_input, str(exc)
            )
        return _error_translation(call_id, localized_name, localized_input, str(exc))

    provider_metadata = dict(part.get("provider_metadata") or {})
    if native_type == "responses_client_tool":
        assert projection is not None
        provider_metadata["responses_client_tool"] = {
            "item_type": projection.native_item_type,
            "execution": projection.execution,
        }
    native_part = {
        "type": "tool_call",
        "tool_call_id": call_id,
        "tool_name": native_name,
        "tool_input": native_input,
        "tool_type": "function"
        if native_type == "responses_client_tool"
        else native_type,
    }
    if "tool_call_index" in part:
        native_part["tool_call_index"] = part["tool_call_index"]
    if provider_metadata:
        native_part["provider_metadata"] = provider_metadata

    return TranslatedToolCall(
        part=native_part,
        mapping=LocalizedToolMapping(
            call_id=call_id,
            localized_name=localized_name,
            localized_input=localized_input,
            native_name=native_name,
            native_input=native_input,
            native_type=native_type,
        ),
    )


def _translate_localized_call(
    localized_name: str,
    localized_input: dict[str, Any],
    *,
    projection: ExecToolProjection | None,
    capabilities: NativeToolCapabilities | None,
    read_cache: ReadOutputCache | None,
    use_apply_patch: bool,
    exec_projections: dict[str, ExecToolProjection] | None,
) -> tuple[str, Any, str]:
    """Dispatch one validated localized call to its execution adapter."""
    if projection is not None and projection.input_mode == "responses_client_tool":
        if not projection.native_item_type or projection.execution != "client":
            raise ValueError("native client tool projection is incomplete")
        return localized_name, localized_input, "responses_client_tool"
    if projection is not None:
        return (
            "exec",
            {"input": build_exec_script(projection, localized_input)},
            "custom",
        )
    if localized_name == "send_line":
        return _localized_send_line_to_native(localized_input)
    return _localized_call_to_native(
        localized_name,
        localized_input,
        capabilities=capabilities or NativeToolCapabilities(),
        read_cache=read_cache,
        use_apply_patch=use_apply_patch,
        apply_patch_exec_projection=(exec_projections or {}).get("apply_patch"),
    )


class LocalizedToolCallStreamTransformer:
    """Buffer localized streaming tool calls and emit native Codex calls."""

    def __init__(
        self,
        *,
        store: CodexToolLocalizationStore | None = None,
        on_mapping: Any | None = None,
        capabilities: NativeToolCapabilities | None = None,
        read_cache: ReadOutputCache | None = None,
        use_apply_patch: bool = DEFAULT_USE_APPLY_PATCH_FOR_CODE_EDITS,
        exec_projections: dict[str, ExecToolProjection] | None = None,
    ) -> None:
        self._store = store
        self._on_mapping = on_mapping
        self._capabilities = capabilities or NativeToolCapabilities()
        self._use_apply_patch = use_apply_patch
        self._read_cache = read_cache
        self._exec_projections = exec_projections or {}
        self._pending: OrderedDict[str, dict[str, Any]] = OrderedDict()

    def transform(self, event: dict[str, Any]) -> list[dict[str, Any]]:
        """Transform one IR stream event into zero or more IR events."""
        event_type = event.get("type")

        if event_type == "tool_call_start" and (
            event.get("tool_name") in _recognized_localized_code_tool_names()
            or event.get("tool_name") in self._exec_projections
        ):
            call_id = event.get("tool_call_id", "")
            if call_id:
                self._pending[call_id] = {
                    "start": dict(event),
                    "arguments": "",
                }
            return []

        if event_type == "tool_call_delta":
            call_id = event.get("tool_call_id", "")
            if call_id in self._pending:
                self._pending[call_id]["arguments"] += event.get("arguments_delta", "")
                return []

        if event_type in ("finish", "stream_end"):
            flushed = self.flush()
            return flushed + [event]

        return [event]

    def flush(self) -> list[dict[str, Any]]:
        """Flush buffered localized calls as Codex-native stream events."""
        events: list[dict[str, Any]] = []
        while self._pending:
            _call_id, buffered = self._pending.popitem(last=False)
            start = buffered["start"]
            part = {
                "type": "tool_call",
                "tool_call_id": start.get("tool_call_id", ""),
                "tool_name": start.get("tool_name", ""),
                "tool_input": _parse_stream_arguments(buffered["arguments"]),
            }
            if "tool_call_index" in start:
                part["tool_call_index"] = start["tool_call_index"]
            if "provider_metadata" in start:
                part["provider_metadata"] = start["provider_metadata"]

            translated = translate_localized_tool_call_part(
                part,
                capabilities=self._capabilities,
                read_cache=self._read_cache,
                use_apply_patch=self._use_apply_patch,
                exec_projections=self._exec_projections,
            )
            if translated is None:
                events.append(start)
                if buffered["arguments"]:
                    events.append(
                        {
                            "type": "tool_call_delta",
                            "tool_call_id": start.get("tool_call_id", ""),
                            "arguments_delta": buffered["arguments"],
                            **_copy_stream_indices(start),
                        }
                    )
                continue

            if self._store is not None:
                self._store.remember(translated.mapping)
            if self._on_mapping is not None:
                self._on_mapping(translated.mapping)
            native_part = translated.part
            start_event = {
                "type": "tool_call_start",
                "tool_call_id": native_part["tool_call_id"],
                "tool_name": native_part["tool_name"],
                "tool_type": native_part.get("tool_type", "function"),
                **_copy_stream_indices(start),
            }
            if "provider_metadata" in native_part:
                start_event["provider_metadata"] = native_part["provider_metadata"]
            events.append(start_event)

            events.append(
                {
                    "type": "tool_call_delta",
                    "tool_call_id": native_part["tool_call_id"],
                    "arguments_delta": _serialize_native_stream_arguments(native_part),
                    **_copy_stream_indices(start),
                }
            )
        return events


def generated_patch_for_edit(
    file_path: str,
    old_string: str,
    new_string: str,
) -> str:
    """Generate a Codex apply_patch update for one exact replacement."""
    return "\n".join(
        [
            "*** Begin Patch",
            f"*** Update File: {file_path}",
            "@@",
            *_prefixed_patch_lines(old_string, "-"),
            *_prefixed_patch_lines(new_string, "+"),
            "*** End Patch",
            "",
        ]
    )


def generated_patch_for_write(args: dict[str, Any]) -> str:
    """Generate a Codex apply_patch add-file patch for Write."""
    file_path = _required_string(args, "file_path", tool_name="Write")
    content = _required_string(args, "content", tool_name="Write")
    return "\n".join(
        [
            "*** Begin Patch",
            f"*** Add File: {file_path}",
            *_prefixed_patch_lines(content, "+"),
            "*** End Patch",
            "",
        ]
    )


def generated_apply_patch_heredoc_command(patch: str) -> str:
    """Generate a shell command that Codex exec_command can intercept."""
    marker = "PATCH"
    while marker in patch:
        marker += "_EOF"
    return f"apply_patch <<'{marker}'\n{patch}{marker}\n"


def generated_command_for_read(args: dict[str, Any]) -> str:
    """Generate a Codex exec_command shell command for Read."""
    file_path = _required_string(args, "file_path", tool_name="Read")
    offset = _optional_int(args, "offset")
    limit = _optional_int(args, "limit")
    script = (
        "from pathlib import Path\n"
        "import sys\n"
        "path = Path(sys.argv[1])\n"
        "offset = int(sys.argv[2]) if sys.argv[2] else None\n"
        "limit = int(sys.argv[3]) if sys.argv[3] else None\n"
        "text = path.read_text(encoding='utf-8')\n"
        "lines = text.splitlines(True)\n"
        "start = max((offset or 1) - 1, 0)\n"
        "end = None if limit is None else start + max(limit, 0)\n"
        "sys.stdout.write(''.join(lines[start:end]))\n"
    )
    return _python_command(
        script,
        file_path,
        "" if offset is None else offset,
        "" if limit is None else limit,
    )


def generated_command_for_glob(args: dict[str, Any]) -> str:
    """Generate a Codex exec_command shell command for Glob."""
    pattern = _required_string(args, "pattern", tool_name="Glob")
    path = str(args.get("path") or ".")
    script = (
        "import glob\n"
        "import os\n"
        "import sys\n"
        "pattern, base = sys.argv[1], sys.argv[2]\n"
        "query = pattern if os.path.isabs(pattern) else os.path.join(base, pattern)\n"
        "for item in sorted(glob.glob(query, recursive=True)):\n"
        "    print(item)\n"
    )
    return _python_command(script, pattern, path)


def generated_command_for_grep(args: dict[str, Any]) -> str:
    """Generate a Codex exec_command shell command for Grep."""
    pattern = _required_string(args, "pattern", tool_name="Grep")
    path = str(args.get("path") or ".")
    command: list[str] = ["rg", "--color=never"]

    output_mode = args.get("output_mode")
    if output_mode == "files_with_matches":
        command.append("--files-with-matches")
    elif output_mode == "count":
        command.append("--count")
    else:
        command.append("--line-number")

    if args.get("case_insensitive"):
        command.append("--ignore-case")
    if args.get("multiline"):
        command.append("--multiline")
    if args.get("glob"):
        command.extend(["-g", str(args["glob"])])
    if args.get("type"):
        command.extend(["-t", str(args["type"])])

    context = _optional_int(args, "context")
    before_context = _optional_int(args, "before_context")
    after_context = _optional_int(args, "after_context")
    if context is not None:
        command.extend(["-C", str(context)])
    if before_context is not None:
        command.extend(["-B", str(before_context)])
    if after_context is not None:
        command.extend(["-A", str(after_context)])

    command.extend(["--", pattern, path])
    rendered = " ".join(shlex.quote(part) for part in command)
    head_limit = _optional_int(args, "head_limit")
    if head_limit is not None and head_limit > 0:
        rendered += " | " + " ".join(["head", "-n", shlex.quote(str(head_limit))])
    return rendered


def generated_command_for_write(args: dict[str, Any]) -> str:
    """Generate a Codex exec_command shell command for Write."""
    file_path = _required_string(args, "file_path", tool_name="Write")
    content = _required_string(args, "content", tool_name="Write")
    encoded = base64.b64encode(content.encode("utf-8")).decode("ascii")
    script = (
        "from pathlib import Path\n"
        "import base64\n"
        "import sys\n"
        "path = Path(sys.argv[1])\n"
        "content = base64.b64decode(sys.argv[2]).decode('utf-8')\n"
        "path.parent.mkdir(parents=True, exist_ok=True)\n"
        "path.write_text(content, encoding='utf-8')\n"
        "print(f'Wrote {len(content)} bytes to {path}')\n"
    )
    return _python_command(script, file_path, encoded)


def generated_command_for_replace_all(args: dict[str, Any]) -> str:
    """Generate a Codex exec_command shell command for Edit replace_all."""
    file_path = _required_string(args, "file_path", tool_name="Edit")
    old_string = _required_string(args, "old_string", tool_name="Edit")
    new_string = _required_string(args, "new_string", tool_name="Edit")
    old_encoded = base64.b64encode(old_string.encode("utf-8")).decode("ascii")
    new_encoded = base64.b64encode(new_string.encode("utf-8")).decode("ascii")
    script = (
        "from pathlib import Path\n"
        "import base64\n"
        "import sys\n"
        "path = Path(sys.argv[1])\n"
        "old = base64.b64decode(sys.argv[2]).decode('utf-8')\n"
        "new = base64.b64decode(sys.argv[3]).decode('utf-8')\n"
        "text = path.read_text(encoding='utf-8')\n"
        "count = text.count(old)\n"
        "if count == 0:\n"
        "    print(f'Edit failed: old_string was not found in {path}', file=sys.stderr)\n"
        "    raise SystemExit(1)\n"
        "path.write_text(text.replace(old, new), encoding='utf-8')\n"
        "print(f'Replaced {count} occurrence(s) in {path}')\n"
    )
    return _python_command(script, file_path, old_encoded, new_encoded)


def generated_command_for_edit_exact(args: dict[str, Any]) -> str:
    """Generate a Codex exec_command shell command for one exact Edit."""
    file_path = _required_string(args, "file_path", tool_name="Edit")
    old_string = _required_string(args, "old_string", tool_name="Edit")
    new_string = _required_string(args, "new_string", tool_name="Edit")
    old_encoded = base64.b64encode(old_string.encode("utf-8")).decode("ascii")
    new_encoded = base64.b64encode(new_string.encode("utf-8")).decode("ascii")
    script = (
        "from pathlib import Path\n"
        "import base64\n"
        "import sys\n"
        "path = Path(sys.argv[1])\n"
        "old = base64.b64decode(sys.argv[2]).decode('utf-8')\n"
        "new = base64.b64decode(sys.argv[3]).decode('utf-8')\n"
        "text = path.read_text(encoding='utf-8')\n"
        "count = text.count(old)\n"
        "if count == 0:\n"
        "    print(f'Edit failed: old_string was not found in {path}', file=sys.stderr)\n"
        "    raise SystemExit(1)\n"
        "if count > 1:\n"
        "    print(f'Edit failed: old_string matched {count} times in {path}', file=sys.stderr)\n"
        "    raise SystemExit(1)\n"
        "path.write_text(text.replace(old, new, 1), encoding='utf-8')\n"
        "print(f'Replaced 1 occurrence in {path}')\n"
    )
    return _python_command(script, file_path, old_encoded, new_encoded)


def _localized_call_to_native(
    localized_name: str,
    localized_input: dict[str, Any],
    *,
    capabilities: NativeToolCapabilities,
    read_cache: ReadOutputCache | None = None,
    use_apply_patch: bool = DEFAULT_USE_APPLY_PATCH_FOR_CODE_EDITS,
    apply_patch_exec_projection: ExecToolProjection | None = None,
) -> tuple[str, Any, str]:
    if localized_name == "Bash":
        command = _required_string(localized_input, "command", tool_name="Bash")
        tool_input: dict[str, Any] = {"cmd": command}
        timeout = _optional_int(localized_input, "timeout")
        if timeout is not None:
            tool_input["yield_time_ms"] = max(250, min(timeout, 30_000))
        if localized_input.get("run_in_background"):
            tool_input.setdefault("yield_time_ms", 1_000)
        return "exec_command", tool_input, "function"

    if localized_name == "Read":
        return (
            "exec_command",
            {
                "cmd": generated_command_for_read(localized_input),
                "yield_time_ms": 1_000,
                "max_output_tokens": 20_000,
            },
            "function",
        )

    if localized_name == "Glob":
        return (
            "exec_command",
            {
                "cmd": generated_command_for_glob(localized_input),
                "yield_time_ms": 1_000,
                "max_output_tokens": 20_000,
            },
            "function",
        )

    if localized_name == "Grep":
        return (
            "exec_command",
            {
                "cmd": generated_command_for_grep(localized_input),
                "yield_time_ms": 1_000,
                "max_output_tokens": 20_000,
            },
            "function",
        )

    if localized_name == "Edit":
        return _localized_edit_to_native(
            localized_input,
            capabilities=capabilities,
            read_cache=read_cache,
            use_apply_patch=use_apply_patch,
            apply_patch_exec_projection=apply_patch_exec_projection,
        )

    if localized_name == "Write":
        if use_apply_patch and capabilities.has_custom_apply_patch:
            return (
                "apply_patch",
                {"input": generated_patch_for_write(localized_input)},
                "custom",
            )
        if (
            use_apply_patch
            and capabilities.has_custom_exec
            and apply_patch_exec_projection is not None
        ):
            return _localized_apply_patch_to_exec(
                generated_patch_for_write(localized_input),
                apply_patch_exec_projection,
            )
        if not use_apply_patch and capabilities.has_exec_command:
            return (
                "exec_command",
                {
                    "cmd": generated_command_for_write(localized_input),
                    "yield_time_ms": 1_000,
                    "max_output_tokens": 20_000,
                },
                "function",
            )
        if capabilities.has_exec_command:
            return (
                "exec_command",
                {
                    "cmd": generated_apply_patch_heredoc_command(
                        generated_patch_for_write(localized_input)
                    ),
                    "yield_time_ms": 1_000,
                    "max_output_tokens": 20_000,
                },
                "function",
            )
        raise ValueError("Write requires apply_patch or exec_command support.")

    raise ValueError(f"Unsupported localized tool: {localized_name}")


def _localized_send_line_to_native(
    localized_input: dict[str, Any],
) -> tuple[str, dict[str, Any], str]:
    """Translate the explicit line facade without changing raw write_stdin."""
    session_id = localized_input.get("session_id")
    line = localized_input.get("line")
    if isinstance(session_id, bool) or not isinstance(session_id, int):
        raise ValueError("send_line requires integer field 'session_id'")
    if not isinstance(line, str):
        raise ValueError("send_line requires string field 'line'")
    return (
        "write_stdin",
        {"session_id": session_id, "chars": f"{line}\n"},
        "function",
    )


def _localized_edit_to_native(
    localized_input: dict[str, Any],
    *,
    capabilities: NativeToolCapabilities,
    read_cache: ReadOutputCache | None = None,
    use_apply_patch: bool = DEFAULT_USE_APPLY_PATCH_FOR_CODE_EDITS,
    apply_patch_exec_projection: ExecToolProjection | None = None,
) -> tuple[str, Any, str]:
    if localized_input.get("replace_all"):
        return (
            "exec_command",
            {
                "cmd": generated_command_for_replace_all(localized_input),
                "yield_time_ms": 1_000,
                "max_output_tokens": 20_000,
            },
            "function",
        )
    file_path = _required_string(localized_input, "file_path", tool_name="Edit")
    old_string = _required_string(localized_input, "old_string", tool_name="Edit")
    new_string = _required_string(localized_input, "new_string", tool_name="Edit")
    if old_string == "":
        raise ValueError("Edit old_string must not be empty.")
    if read_cache is not None:
        expanded = read_cache.expand_edit(
            file_path=file_path,
            old_string=old_string,
            new_string=new_string,
        )
        if expanded is not None:
            old_string, new_string = expanded
            localized_input = {
                **localized_input,
                "old_string": old_string,
                "new_string": new_string,
            }
    if not use_apply_patch:
        if capabilities.has_exec_command:
            return (
                "exec_command",
                {
                    "cmd": generated_command_for_edit_exact(localized_input),
                    "yield_time_ms": 1_000,
                    "max_output_tokens": 20_000,
                },
                "function",
            )
        raise ValueError("Edit requires exec_command support.")
    patch = generated_patch_for_edit(file_path, old_string, new_string)
    if not capabilities.has_custom_apply_patch:
        if capabilities.has_custom_exec and apply_patch_exec_projection is not None:
            return _localized_apply_patch_to_exec(
                patch,
                apply_patch_exec_projection,
            )
        if capabilities.has_exec_command:
            return (
                "exec_command",
                {
                    "cmd": generated_apply_patch_heredoc_command(patch),
                    "yield_time_ms": 1_000,
                    "max_output_tokens": 20_000,
                },
                "function",
            )
        if capabilities.has_shell_command:
            return (
                "shell_command",
                {"command": generated_apply_patch_heredoc_command(patch)},
                "function",
            )
        raise ValueError("Edit requires apply_patch or exec_command support.")
    return (
        "apply_patch",
        {"input": patch},
        "custom",
    )


def _localized_apply_patch_to_exec(
    patch: str,
    projection: ExecToolProjection,
) -> tuple[str, dict[str, str], str]:
    """Route a localized edit through Code Mode's nested apply_patch tool."""
    return (
        "exec",
        {
            "input": build_exec_script(
                projection,
                {projection.input_field: patch},
            )
        },
        "custom",
    )


def _catalog_injection_definitions() -> list[dict[str, Any]]:
    """Return independent localized definitions owned by the catalog."""
    definitions: list[dict[str, Any]] = []
    for item_id in tool_catalog_lookups()["items"]:
        if not set(catalog_runtime_adapters(item_id)).intersection(
            {"localized_file_tool", "send_line"}
        ):
            continue
        definition = catalog_tool_definition(item_id)
        if definition is None:
            raise ValueError(f"catalog adapter item {item_id!r} needs a definition")
        definitions.append(definition)
    return definitions


def _localize_history_message(
    message: Any,
    store: CodexToolLocalizationStore | None,
    mappings: list[LocalizedToolMapping] | None = None,
    *,
    used_call_ids: set[str] | None = None,
) -> Any:
    if not isinstance(message, dict) or message.get("role") != "assistant":
        return message
    tool_calls = message.get("tool_calls")
    if not isinstance(tool_calls, list):
        return message

    changed = False
    localized_tool_calls: list[Any] = []
    for tool_call in tool_calls:
        localized = _localize_history_tool_call(
            tool_call,
            store,
            mappings,
            used_call_ids=used_call_ids,
        )
        changed = changed or localized is not tool_call
        localized_tool_calls.append(localized)
    if not changed:
        return message

    adapted = dict(message)
    adapted["tool_calls"] = localized_tool_calls
    return adapted


def _update_read_output_cache_from_message(
    message: Any,
    cache: ReadOutputCache,
) -> None:
    if not isinstance(message, dict):
        return
    if message.get("role") == "assistant":
        tool_calls = message.get("tool_calls")
        if not isinstance(tool_calls, list):
            return
        for tool_call in tool_calls:
            read_call = _read_call_from_tool_call(tool_call)
            if read_call is not None:
                cache.remember_read_call(read_call.call_id, read_call.file_path)
                continue
            mutating_call = _mutating_call_from_tool_call(tool_call)
            if mutating_call is not None:
                cache.remember_mutating_call(
                    mutating_call.call_id,
                    mutating_call.file_path,
                )
        return

    if message.get("role") == "tool":
        call_id = str(message.get("tool_call_id") or "")
        content = _tool_message_text(message.get("content"))
        if call_id and content is not None:
            cache.remember_tool_output(call_id, content)


def _read_call_from_tool_call(tool_call: Any) -> ReadCall | None:
    if not isinstance(tool_call, dict):
        return None
    function = tool_call.get("function")
    if not isinstance(function, dict) or function.get("name") != "Read":
        return None
    try:
        args = json.loads(function.get("arguments") or "{}")
    except json.JSONDecodeError:
        return None
    if not isinstance(args, dict) or not isinstance(args.get("file_path"), str):
        return None
    call_id = str(tool_call.get("id") or "")
    if not call_id:
        return None
    return ReadCall(call_id=call_id, file_path=args["file_path"])


def _mutating_call_from_tool_call(tool_call: Any) -> ReadCall | None:
    if not isinstance(tool_call, dict):
        return None
    function = tool_call.get("function")
    if not isinstance(function, dict) or function.get("name") not in {"Edit", "Write"}:
        return None
    try:
        args = json.loads(function.get("arguments") or "{}")
    except json.JSONDecodeError:
        return None
    if not isinstance(args, dict) or not isinstance(args.get("file_path"), str):
        return None
    call_id = str(tool_call.get("id") or "")
    if not call_id:
        return None
    return ReadCall(call_id=call_id, file_path=args["file_path"])


def _tool_message_text(content: Any) -> str | None:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for part in content:
            if isinstance(part, dict):
                text = part.get("text")
                if isinstance(text, str):
                    parts.append(text)
            elif isinstance(part, str):
                parts.append(part)
        return "\n".join(parts)
    return None


def _tool_output_indicates_failure(text: str) -> bool:
    lowered = text.lower()
    return (
        "exit code: 1" in lowered
        or "apply_patch verification failed" in lowered
        or "edit failed:" in lowered
        or "tool adaptation error:" in lowered
    )


def _localize_history_tool_call(
    tool_call: Any,
    store: CodexToolLocalizationStore | None,
    mappings: list[LocalizedToolMapping] | None = None,
    *,
    used_call_ids: set[str] | None = None,
) -> Any:
    if not isinstance(tool_call, dict):
        return tool_call
    function = tool_call.get("function")
    if not isinstance(function, dict):
        return tool_call
    call_id = tool_call.get("id", "")
    mapping = store.get(call_id) if store is not None else None
    if mapping is None:
        mapping = _mapping_for_codex_tool_call(
            tool_call,
            mappings or [],
        )
    if mapping is not None and used_call_ids is not None:
        used_call_ids.add(mapping.call_id)
    if mapping is None:
        name = function.get("name")
        if name != "exec_command":
            return tool_call
        try:
            native_args = json.loads(function.get("arguments") or "{}")
        except json.JSONDecodeError:
            return tool_call
        cmd = native_args.get("cmd")
        if not isinstance(cmd, str):
            return tool_call
        localized_name = "Bash"
        localized_input = {"command": cmd}
    else:
        localized_name = mapping.localized_name
        localized_input = mapping.localized_input

    adapted = dict(tool_call)
    adapted_function = dict(function)
    adapted_function["name"] = localized_name
    adapted_function["arguments"] = json.dumps(localized_input, ensure_ascii=False)
    adapted["function"] = adapted_function
    return adapted


def _mapping_for_codex_tool_call(
    tool_call: dict[str, Any],
    mappings: list[LocalizedToolMapping],
) -> LocalizedToolMapping | None:
    for mapping in mappings:
        if _tool_call_matches_mapping(
            tool_call,
            mapping,
        ):
            return mapping
    return None


def _tool_call_matches_mapping(
    tool_call: dict[str, Any],
    mapping: LocalizedToolMapping,
) -> bool:
    if tool_call.get("id") != mapping.call_id:
        return False
    function = tool_call.get("function")
    if not isinstance(function, dict) or function.get("name") != mapping.native_name:
        return False
    try:
        args = json.loads(function.get("arguments") or "{}")
    except json.JSONDecodeError:
        return False
    return args == mapping.native_input


def _chat_tool_call(call_id: str, name: str, arguments: Any) -> dict[str, Any]:
    return {
        "id": call_id,
        "type": "function",
        "function": {
            "name": name,
            "arguments": json.dumps(arguments, ensure_ascii=False)
            if isinstance(arguments, dict)
            else str(arguments),
        },
    }


def localized_mapping_from_tool_calls(
    original_tool_call: dict[str, Any],
    codex_tool_call: dict[str, Any],
) -> LocalizedToolMapping | None:
    """Rebuild a localized mapping from persisted Chat tool-call shapes."""
    original_function = original_tool_call.get("function")
    codex_function = codex_tool_call.get("function")
    if not isinstance(original_function, dict) or not isinstance(codex_function, dict):
        return None
    call_id = str(codex_tool_call.get("id") or original_tool_call.get("id") or "")
    if not call_id:
        return None
    localized_name = original_function.get("name")
    native_name = codex_function.get("name")
    if not isinstance(localized_name, str) or not isinstance(native_name, str):
        return None
    try:
        localized_input = json.loads(original_function.get("arguments") or "{}")
        native_input = json.loads(codex_function.get("arguments") or "{}")
    except json.JSONDecodeError:
        return None
    if not isinstance(localized_input, dict):
        return None
    stored_native_type = codex_tool_call.get("_codex_rosetta_native_type")
    native_type = (
        stored_native_type
        if isinstance(stored_native_type, str)
        else ("custom" if native_name in {"apply_patch", "exec"} else "function")
    )
    return LocalizedToolMapping(
        call_id=call_id,
        localized_name=localized_name,
        localized_input=localized_input,
        native_name=native_name,
        native_input=native_input,
        native_type=native_type,
    )


def _chat_tool_name(tool: Any) -> str | None:
    if not isinstance(tool, dict):
        return None
    if tool.get("type") == "function":
        function = tool.get("function")
        if isinstance(function, dict) and function.get("name"):
            return function["name"]
        if tool.get("name"):
            return tool["name"]
    return tool.get("name") or tool.get("type")


def _chat_tool_type(tool: Any) -> str | None:
    return tool.get("type") if isinstance(tool, dict) else None


def _tool_choice_name(tool_choice: Any) -> str | None:
    if isinstance(tool_choice, str):
        return tool_choice
    if not isinstance(tool_choice, dict):
        return None
    if tool_choice.get("tool_name"):
        return tool_choice["tool_name"]
    function = tool_choice.get("function")
    if isinstance(function, dict):
        return function.get("name")
    return tool_choice.get("name")


def _ensure_input_dict(value: Any) -> dict[str, Any] | None:
    return value if isinstance(value, dict) else None


def _parse_stream_arguments(arguments: str) -> dict[str, Any]:
    try:
        parsed = json.loads(arguments) if arguments else {}
    except json.JSONDecodeError:
        return {"raw_arguments": arguments}
    return parsed if isinstance(parsed, dict) else {"raw_arguments": arguments}


def _serialize_native_stream_arguments(native_part: dict[str, Any]) -> str:
    tool_input = native_part.get("tool_input", {})
    if native_part.get("tool_type") == "custom":
        if isinstance(tool_input, dict) and set(tool_input) == {"input"}:
            return str(tool_input["input"])
        return json.dumps(tool_input, ensure_ascii=False)
    return json.dumps(
        tool_input if isinstance(tool_input, dict) else {},
        ensure_ascii=False,
    )


def _copy_stream_indices(event: dict[str, Any]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    if "tool_call_index" in event:
        result["tool_call_index"] = event["tool_call_index"]
    if "choice_index" in event:
        result["choice_index"] = event["choice_index"]
    return result


def _error_translation(
    call_id: str,
    localized_name: str,
    localized_input: dict[str, Any],
    message: str,
) -> TranslatedToolCall:
    native_input = {
        "cmd": "printf '%s\\n' "
        + shlex.quote(f"Tool adaptation error: {message}")
        + " >&2; exit 1",
        "yield_time_ms": 1_000,
        "max_output_tokens": 2_000,
    }
    return TranslatedToolCall(
        part={
            "type": "tool_call",
            "tool_call_id": call_id,
            "tool_name": "exec_command",
            "tool_input": native_input,
            "tool_type": "function",
        },
        mapping=LocalizedToolMapping(
            call_id=call_id,
            localized_name=localized_name,
            localized_input=localized_input,
            native_name="exec_command",
            native_input=native_input,
            native_type="function",
        ),
    )


def _exec_error_translation(
    call_id: str,
    localized_name: str,
    localized_input: dict[str, Any],
    message: str,
) -> TranslatedToolCall:
    """Return a valid exec call that reports a projection error to Codex."""
    script = "text(" + json.dumps(f"Tool adaptation error: {message}") + ");\n"
    native_input = {"input": script}
    return TranslatedToolCall(
        part={
            "type": "tool_call",
            "tool_call_id": call_id,
            "tool_name": "exec",
            "tool_input": native_input,
            "tool_type": "custom",
        },
        mapping=LocalizedToolMapping(
            call_id=call_id,
            localized_name=localized_name,
            localized_input=localized_input,
            native_name="exec",
            native_input=native_input,
            native_type="custom",
        ),
    )


def _required_string(args: dict[str, Any], key: str, *, tool_name: str) -> str:
    value = args.get(key)
    if not isinstance(value, str):
        raise ValueError(f"{tool_name} requires string field '{key}'.")
    return value


def _optional_int(args: dict[str, Any], key: str) -> int | None:
    value = args.get(key)
    if value is None:
        return None
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float) and value.is_integer():
        return int(value)
    return None


def _prefixed_patch_lines(text: str, prefix: str) -> list[str]:
    if text == "":
        return [prefix]
    return [prefix + line for line in text.splitlines()]


def _unwrap_command_output(text: str) -> str:
    marker = "Output:\n"
    if marker in text:
        return text.split(marker, 1)[1]
    return text


def _line_expansion_candidates(
    text: str,
    *,
    old_string: str,
    new_string: str,
) -> list[tuple[str, str]]:
    candidates: list[tuple[str, str]] = []
    start = 0
    while True:
        index = text.find(old_string, start)
        if index < 0:
            return candidates

        before = text[index - 1] if index > 0 else "\n"
        after_index = index + len(old_string)
        after = text[after_index] if after_index < len(text) else "\n"
        if before == "\n" and after == "\n":
            start = index + 1
            continue

        line_start = text.rfind("\n", 0, index) + 1
        line_end = text.find("\n", after_index)
        if line_end < 0:
            line_end = len(text)
        full_old = text[line_start:line_end]
        if old_string in full_old:
            candidates.append((full_old, full_old.replace(old_string, new_string, 1)))
        start = index + 1


def _python_command(script: str, *args: Any) -> str:
    command = ["python3", "-c", script, *[str(arg) for arg in args]]
    return " ".join(shlex.quote(part) for part in command)
