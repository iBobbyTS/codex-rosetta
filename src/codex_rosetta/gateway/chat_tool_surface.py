"""Window-scoped stability for final model-visible Chat tool arrays."""

from __future__ import annotations

import copy
import hashlib
import json
import re
import threading
from dataclasses import dataclass, replace
from datetime import datetime, timedelta, timezone
from typing import Any

from codex_rosetta.routing import ResolvedRoute

from ..observability.chat_tool_surface_store import ChatToolSurfaceConflictError
from .admin.tool_catalog import load_tool_catalog
from .state_scope import GatewayStateScope
from .code_mode_projection import (
    ALL_TOOLS_READ_CHAT_NAME,
    DEFERRED_TOOL_DISPATCH_CHAT_NAME,
    ExecDescriptionSection,
    ExecToolProjection,
    plan_exec_tool_definitions,
    prune_exec_tool_description,
)
from .tool_adaptation import DEFERRED_CANDIDATES_KEY, EXEC_PROJECTIONS_KEY
from .tool_profiles import (
    catalog_runtime_adapters,
    route_tool_state,
    tool_catalog_lookups,
)
from .web_run_capabilities import WEB_RUN_PROFILE_ITEM_ID
from .search_provider_contract import SearchProviderCapability

ADAPTER_CONTRACT_VERSION = "chat-tool-surface-v2"


class ChatToolSurfaceUnavailable(RuntimeError):
    """A persistent window surface could not be read or written safely."""


@dataclass(frozen=True)
class ChatToolSurfaceDecision:
    """Final upstream body and privacy-safe decision metadata."""

    body: dict[str, Any]
    profile: dict[str, Any]


class InMemoryChatToolSurfaceStore:
    """Process-local store with the same first-writer and TTL contract."""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._items: dict[bytes, tuple[dict[str, Any], datetime]] = {}

    def load_or_create(
        self,
        *,
        principal_id: str,
        scope: dict[str, Any],
        initial_payload: dict[str, Any],
        now: datetime | None = None,
    ) -> tuple[dict[str, Any], bool]:
        current = _now(now)
        key = _memory_key(principal_id, scope)
        with self._lock:
            self._cleanup(current)
            item = self._items.get(key)
            if item is not None:
                payload, _expiry = item
                self._items[key] = (payload, current + timedelta(hours=24))
                return copy.deepcopy(payload), False
            payload = {**copy.deepcopy(initial_payload), "scope": copy.deepcopy(scope)}
            self._items[key] = (payload, current + timedelta(hours=24))
            return copy.deepcopy(payload), True

    def replace(
        self,
        *,
        principal_id: str,
        scope: dict[str, Any],
        expected_epoch: int,
        payload: dict[str, Any],
        now: datetime | None = None,
    ) -> dict[str, Any]:
        current = _now(now)
        key = _memory_key(principal_id, scope)
        with self._lock:
            self._cleanup(current)
            item = self._items.get(key)
            if item is None or item[0].get("epoch") != expected_epoch:
                raise ChatToolSurfaceConflictError(
                    "surface snapshot epoch changed concurrently"
                )
            replacement = {**copy.deepcopy(payload), "scope": copy.deepcopy(scope)}
            self._items[key] = (replacement, current + timedelta(hours=24))
            return copy.deepcopy(replacement)

    def _cleanup(self, current: datetime) -> None:
        expired = [
            key for key, (_payload, expiry) in self._items.items() if expiry <= current
        ]
        for key in expired:
            self._items.pop(key, None)


class ChatToolSurfaceCoordinator:
    """Coordinate one final tool array after projection and before transport."""

    def __init__(self, in_memory_store: InMemoryChatToolSurfaceStore) -> None:
        self._in_memory_store = in_memory_store

    def apply(
        self,
        body: dict[str, Any],
        *,
        route: ResolvedRoute,
        state_scope: GatewayStateScope,
        codex_window_id: str | None,
        persistence: Any | None,
    ) -> ChatToolSurfaceDecision:
        """Lock or roll over the eligible window's final ordered Chat tools."""
        carrier_index, carrier_tools = _tool_carrier(body)
        if not _eligible(
            route=route,
            state_scope=state_scope,
            codex_window_id=codex_window_id,
            tools=carrier_tools,
        ):
            return ChatToolSurfaceDecision(body=body, profile={})

        store = persistence or self._in_memory_store
        scope = _surface_scope(
            route=route,
            state_scope=state_scope,
            window_id=codex_window_id or "",
        )
        candidate_tools = copy.deepcopy(carrier_tools)
        candidate_hash = _canonical_hash(candidate_tools)
        initial = _snapshot(
            candidate_tools,
            epoch=0,
            reason="initial",
            web_run_capabilities=route.web_run_search_capabilities,
        )
        try:
            snapshot, created = (
                persistence.load_or_create_chat_tool_surface(
                    principal_id=state_scope.principal_id,
                    scope=scope,
                    initial_payload=initial,
                )
                if persistence is not None
                else self._in_memory_store.load_or_create(
                    principal_id=state_scope.principal_id,
                    scope=scope,
                    initial_payload=initial,
                )
            )
            return self._resolve(
                body=body,
                route=route,
                carrier_index=carrier_index,
                candidate_tools=candidate_tools,
                candidate_hash=candidate_hash,
                snapshot=snapshot,
                created=created,
                store=store,
                persistence=persistence,
                principal_id=state_scope.principal_id,
                scope=scope,
            )
        except ChatToolSurfaceConflictError:
            raise ChatToolSurfaceUnavailable(
                "window tool surface changed concurrently; retry the request"
            ) from None
        except ChatToolSurfaceUnavailable:
            raise
        except Exception as exc:
            raise ChatToolSurfaceUnavailable(
                "window tool surface persistence is unavailable"
            ) from exc

    def locked_web_run_capabilities(
        self,
        *,
        route: ResolvedRoute,
        state_scope: GatewayStateScope,
        codex_window_id: str | None,
        persistence: Any | None,
    ) -> frozenset[SearchProviderCapability] | None:
        """Read the first window surface's typed web.run capability contract."""
        if not (
            codex_window_id
            and state_scope.persistent
            and route.source_provider in {"openai_responses", "open_responses"}
            and route.tool_profile_name is not None
            and route_tool_state(route, WEB_RUN_PROFILE_ITEM_ID) == "modified"
        ):
            return None
        scope = _surface_scope(
            route=route,
            state_scope=state_scope,
            window_id=codex_window_id,
        )
        initial = _snapshot(
            [],
            epoch=0,
            reason="capability_read",
            web_run_capabilities=route.web_run_search_capabilities,
        )
        try:
            snapshot, _created = (
                persistence.load_or_create_chat_tool_surface(
                    principal_id=state_scope.principal_id,
                    scope=scope,
                    initial_payload=initial,
                )
                if persistence is not None
                else self._in_memory_store.load_or_create(
                    principal_id=state_scope.principal_id,
                    scope=scope,
                    initial_payload=initial,
                )
            )
            values = snapshot.get("web_run_capabilities")
            if not isinstance(values, list) or not all(
                isinstance(value, str) for value in values
            ):
                raise ChatToolSurfaceUnavailable(
                    "stored window web.run capabilities are invalid"
                )
            return frozenset(SearchProviderCapability(value) for value in values)
        except ChatToolSurfaceUnavailable:
            raise
        except Exception as exc:
            raise ChatToolSurfaceUnavailable(
                "window tool surface persistence is unavailable"
            ) from exc

    @staticmethod
    def _replace_snapshot(
        *,
        store: Any,
        persistence: Any | None,
        principal_id: str,
        scope: dict[str, Any],
        expected_epoch: int,
        replacement: dict[str, Any],
    ) -> dict[str, Any]:
        if persistence is not None:
            return store.replace_chat_tool_surface(
                principal_id=principal_id,
                scope=scope,
                expected_epoch=expected_epoch,
                payload=replacement,
            )
        return store.replace(
            principal_id=principal_id,
            scope=scope,
            expected_epoch=expected_epoch,
            payload=replacement,
        )

    def _resolve(
        self,
        *,
        body: dict[str, Any],
        route: ResolvedRoute,
        carrier_index: int | None,
        candidate_tools: list[Any],
        candidate_hash: str,
        snapshot: dict[str, Any],
        created: bool,
        store: Any,
        persistence: Any | None,
        principal_id: str,
        scope: dict[str, Any],
    ) -> ChatToolSurfaceDecision:
        baseline_tools = snapshot.get("tools")
        if not isinstance(baseline_tools, list):
            raise ChatToolSurfaceUnavailable("stored window tool surface is invalid")
        baseline_hash = str(
            snapshot.get("tool_hash") or _canonical_hash(baseline_tools)
        )
        added, removed, changed, opaque = _diff_tools(baseline_tools, candidate_tools)
        metadata = {
            "chat_tool_surface_generation": scope["contract_generation"],
            "chat_tool_surface_epoch": int(snapshot["epoch"]),
            "chat_tool_surface_baseline_hash": baseline_hash,
            "chat_tool_surface_current_hash": candidate_hash,
            "chat_tool_surface_added": len(added),
            "chat_tool_surface_removed": len(removed),
            "chat_tool_surface_changed": len(changed),
        }
        if created or not (added or removed or changed or opaque):
            metadata.update(
                chat_tool_surface_final_hash=baseline_hash,
                chat_tool_surface_decision="created" if created else "stable",
                chat_tool_surface_deferred=0,
                chat_tool_surface_stale=0,
            )
            return ChatToolSurfaceDecision(body=body, profile=metadata)

        comparison_body = dict(body)
        comparison_body["tools"] = candidate_tools
        deferred_names = added | changed
        capability_names = deferred_names - {"exec"}
        selected_name = _selected_tool_name(body.get("tool_choice"))
        reliable = (
            not opaque
            and selected_name not in deferred_names
            and all(
                _reliable_deferred_name(comparison_body, name, route=route)
                for name in capability_names
            )
            and (
                "exec" not in changed
                or _reliable_exec_container_change(
                    comparison_body,
                    baseline_tools=baseline_tools,
                    changed_capability_names=(
                        capability_names or _modified_direct_capability_names(route)
                    ),
                )
            )
        )
        if reliable:
            adapted = _replace_tool_carrier(body, carrier_index, baseline_tools)
            _enable_locked_deferred_candidates(adapted, capability_names)
            metadata.update(
                chat_tool_surface_final_hash=baseline_hash,
                chat_tool_surface_decision="locked",
                chat_tool_surface_deferred=len(capability_names),
                chat_tool_surface_stale=len(removed),
            )
            return ChatToolSurfaceDecision(body=adapted, profile=metadata)

        replacement = _snapshot(
            candidate_tools,
            epoch=int(snapshot["epoch"]) + 1,
            reason="opaque_rollover",
            web_run_capabilities=route.web_run_search_capabilities,
        )
        self._replace_snapshot(
            store=store,
            persistence=persistence,
            principal_id=principal_id,
            scope=scope,
            expected_epoch=int(snapshot["epoch"]),
            replacement=replacement,
        )
        metadata.update(
            chat_tool_surface_epoch=replacement["epoch"],
            chat_tool_surface_final_hash=candidate_hash,
            chat_tool_surface_decision="opaque_rollover",
            chat_tool_surface_rollover_reason=(
                "explicit_tool_choice"
                if selected_name in deferred_names
                else "opaque_tool"
            ),
            chat_tool_surface_deferred=0,
            chat_tool_surface_stale=0,
        )
        return ChatToolSurfaceDecision(body=body, profile=metadata)


def apply_chat_tool_surface(
    coordinator: ChatToolSurfaceCoordinator | None,
    body: dict[str, Any],
    *,
    route: ResolvedRoute,
    state_scope: GatewayStateScope,
    codex_window_id: str | None,
    persistence: Any | None,
) -> ChatToolSurfaceDecision:
    """Apply window locking when configured, otherwise preserve the body."""
    if coordinator is None:
        return ChatToolSurfaceDecision(body=body, profile={})
    return coordinator.apply(
        body,
        route=route,
        state_scope=state_scope,
        codex_window_id=codex_window_id,
        persistence=persistence,
    )


def _tool_carrier(body: dict[str, Any]) -> tuple[int | None, Any]:
    """Return the top-level or Responses Lite final tool array."""
    tools = body.get("tools")
    if isinstance(tools, list):
        return None, tools
    input_items = body.get("input")
    if isinstance(input_items, list):
        for index, item in enumerate(input_items):
            if isinstance(item, dict) and item.get("type") == "additional_tools":
                return index, item.get("tools")
    return None, None


def _replace_tool_carrier(
    body: dict[str, Any], carrier_index: int | None, tools: list[Any]
) -> dict[str, Any]:
    adapted = copy.deepcopy(body) if carrier_index is not None else dict(body)
    if carrier_index is None:
        adapted["tools"] = copy.deepcopy(tools)
    else:
        adapted["input"][carrier_index]["tools"] = copy.deepcopy(tools)
    return adapted


def _eligible(
    *,
    route: ResolvedRoute,
    state_scope: GatewayStateScope,
    codex_window_id: str | None,
    tools: Any,
) -> bool:
    return (
        bool(codex_window_id)
        and state_scope.persistent
        and route.source_provider in {"openai_responses", "open_responses"}
        and (
            route.target_provider == "openai_chat"
            or (
                route.target_provider in {"openai_responses", "open_responses"}
                and route_tool_state(route, WEB_RUN_PROFILE_ITEM_ID) == "modified"
            )
        )
        and route.tool_profile_name is not None
        and isinstance(tools, list)
    )


def _surface_scope(
    *, route: ResolvedRoute, state_scope: GatewayStateScope, window_id: str
) -> dict[str, Any]:
    catalog = load_tool_catalog()
    metadata = catalog["metadata"]
    generation_material = {
        "schema_version": metadata["schema_version"],
        "codex_source_commit": metadata["codex_source_commit"],
        "profile_name": route.tool_profile_name,
        "profile": route.tool_profile,
        "profile_inputs": route.tool_profile_inputs,
        "adapter_contract": ADAPTER_CONTRACT_VERSION,
    }
    return {
        "provider": state_scope.provider_name,
        "model": state_scope.model,
        "window_id": window_id,
        "source_api": str(route.source_provider),
        "target_api": str(route.target_provider),
        "contract_generation": _canonical_hash(generation_material),
    }


def _snapshot(
    tools: list[Any],
    *,
    epoch: int,
    reason: str,
    web_run_capabilities: frozenset[object] | None,
) -> dict[str, Any]:
    return {
        "epoch": epoch,
        "tools": copy.deepcopy(tools),
        "tool_hash": _canonical_hash(tools),
        "adapter_manifest": _tool_manifest(tools),
        "reason": reason,
        "web_run_capabilities": sorted(
            capability.value
            for capability in (web_run_capabilities or ())
            if isinstance(capability, SearchProviderCapability)
        ),
    }


def _tool_manifest(tools: list[Any]) -> dict[str, str]:
    manifest: dict[str, str] = {}
    for tool in tools:
        name = _tool_name(tool)
        if name is not None:
            manifest[name] = _canonical_hash(tool)
    return manifest


def _diff_tools(
    baseline: list[Any], current: list[Any]
) -> tuple[set[str], set[str], set[str], bool]:
    baseline_map, baseline_opaque = _tool_map(baseline)
    current_map, current_opaque = _tool_map(current)
    baseline_names = set(baseline_map)
    current_names = set(current_map)
    shared = baseline_names & current_names
    changed = {
        name
        for name in shared
        if _canonical_hash(baseline_map[name]) != _canonical_hash(current_map[name])
    }
    return (
        current_names - baseline_names,
        baseline_names - current_names,
        changed,
        baseline_opaque or current_opaque,
    )


def _tool_map(tools: list[Any]) -> tuple[dict[str, Any], bool]:
    output: dict[str, Any] = {}
    opaque = False
    for tool in tools:
        name = _tool_name(tool)
        if name is None or name in output:
            opaque = True
            continue
        output[name] = tool
    return output, opaque


def _tool_name(tool: Any) -> str | None:
    if not isinstance(tool, dict) or tool.get("type") not in {"function", "custom"}:
        return None
    function = tool.get("function")
    name = function.get("name") if isinstance(function, dict) else None
    if not isinstance(name, str):
        name = tool.get("name")
    return name if isinstance(name, str) and name else None


def _reliable_deferred_name(
    body: dict[str, Any], name: str, *, route: ResolvedRoute
) -> bool:
    candidates = body.get(DEFERRED_CANDIDATES_KEY)
    candidate = candidates.get(name) if isinstance(candidates, dict) else None
    current_tool = _tool_map(body.get("tools", []))[0].get(name)
    if candidate is not None:
        return bool(
            isinstance(candidate, dict)
            and isinstance(candidate.get("projection"), ExecToolProjection)
            and isinstance(candidate.get("definition"), dict)
            and candidate.get("definition_hash")
            and _canonical_hash(candidate["definition"])
            == _canonical_hash(current_tool)
        )

    projections = body.get(EXEC_PROJECTIONS_KEY)
    projection = projections.get(name) if isinstance(projections, dict) else None
    if projection is not None and getattr(projection, "nested_name", ""):
        return getattr(projection, "input_mode", "") in {"args", "freeform"}

    return name in _modified_direct_capability_names(route)


def _modified_direct_capability_names(route: ResolvedRoute) -> set[str]:
    """Resolve reliable direct tool identities from the catalog-owned profile item."""
    if (
        route.target_provider not in {"openai_responses", "open_responses"}
        or route_tool_state(route, WEB_RUN_PROFILE_ITEM_ID) != "modified"
    ):
        return set()
    if "web_run" not in catalog_runtime_adapters(WEB_RUN_PROFILE_ITEM_ID):
        return set()
    item = tool_catalog_lookups()["items"][WEB_RUN_PROFILE_ITEM_ID]
    name = item.get("name")
    return {name} if isinstance(name, str) and name else set()


def _reliable_exec_container_change(
    body: dict[str, Any],
    *,
    baseline_tools: list[Any],
    changed_capability_names: set[str],
) -> bool:
    """Accept an exec description change owned only by reliable nested sections."""
    if not changed_capability_names:
        return False
    baseline_exec = _tool_map(baseline_tools)[0].get("exec")
    current_exec = _tool_map(body.get("tools", []))[0].get("exec")
    baseline_function = _function_definition(baseline_exec)
    current_function = _function_definition(current_exec)
    if baseline_function is None or current_function is None:
        return False
    baseline_description = baseline_function.get("description")
    current_description = current_function.get("description")
    if not isinstance(baseline_description, str) or not isinstance(
        current_description, str
    ):
        return False
    baseline_envelope = dict(baseline_function)
    current_envelope = dict(current_function)
    baseline_envelope.pop("description", None)
    current_envelope.pop("description", None)
    if _canonical_hash(baseline_envelope) != _canonical_hash(current_envelope):
        return False
    if _normalize_exec_description(baseline_description) == _normalize_exec_description(
        current_description
    ):
        return True

    projections = _exec_projection_candidates(body)
    if not changed_capability_names <= set(projections):
        return False
    baseline_plan = plan_exec_tool_definitions(baseline_description, projections)
    current_plan = plan_exec_tool_definitions(current_description, projections)
    if baseline_plan.duplicate_section_names or current_plan.duplicate_section_names:
        return False
    section_names = set(baseline_plan.sections) | set(current_plan.sections)
    differing_sections = {
        name
        for name in section_names
        if (
            baseline_plan.sections.get(name) is None
            or current_plan.sections.get(name) is None
            or baseline_plan.sections[name].raw != current_plan.sections[name].raw
        )
    }
    if differing_sections != changed_capability_names:
        return False
    baseline_remainder = _normalized_exec_remainder(
        baseline_description,
        [
            baseline_plan.sections[name]
            for name in differing_sections
            if name in baseline_plan.sections
        ],
    )
    current_remainder = _normalized_exec_remainder(
        current_description,
        [current_plan.sections[name] for name in differing_sections],
    )
    return baseline_remainder == current_remainder


def _normalized_exec_remainder(
    description: str, sections: list[ExecDescriptionSection]
) -> str:
    """Remove owned sections without treating their separator blank lines as drift."""
    pruned = prune_exec_tool_description(description, sections)
    return _normalize_exec_description(pruned)


def _normalize_exec_description(description: str) -> str:
    """Collapse only blank lines left by exact section pruning."""
    return re.sub(r"\n[ \t]*\n(?:[ \t]*\n)+", "\n\n", description)


def _function_definition(tool: Any) -> dict[str, Any] | None:
    if not isinstance(tool, dict) or tool.get("type") not in {"function", "custom"}:
        return None
    function = tool.get("function")
    return function if isinstance(function, dict) else tool


def _exec_projection_candidates(body: dict[str, Any]) -> dict[str, ExecToolProjection]:
    projections = body.get(EXEC_PROJECTIONS_KEY)
    output = (
        {
            name: projection
            for name, projection in projections.items()
            if isinstance(name, str) and isinstance(projection, ExecToolProjection)
        }
        if isinstance(projections, dict)
        else {}
    )
    candidates = body.get(DEFERRED_CANDIDATES_KEY)
    if isinstance(candidates, dict):
        for name, candidate in candidates.items():
            projection = (
                candidate.get("projection") if isinstance(candidate, dict) else None
            )
            if isinstance(name, str) and isinstance(projection, ExecToolProjection):
                output[name] = projection
    return output


def _enable_locked_deferred_candidates(body: dict[str, Any], names: set[str]) -> None:
    candidates = body.get(DEFERRED_CANDIDATES_KEY)
    projections = body.get(EXEC_PROJECTIONS_KEY)
    if not isinstance(projections, dict):
        return
    active = dict(projections)
    authorized: dict[str, str] = {}
    for name in names:
        candidate = candidates.get(name) if isinstance(candidates, dict) else None
        if not isinstance(candidate, dict):
            active.pop(name, None)
        else:
            current_hash = candidate.get("definition_hash")
            authorized_hash = candidate.get("authorized_definition_hash")
            if (
                isinstance(current_hash, str)
                and isinstance(authorized_hash, str)
                and current_hash == authorized_hash
            ):
                authorized[name] = current_hash
            active.pop(name, None)

    read_projection = active.get(ALL_TOOLS_READ_CHAT_NAME)
    if isinstance(read_projection, ExecToolProjection):
        active[ALL_TOOLS_READ_CHAT_NAME] = replace(
            read_projection,
            dispatch_blocked_names=tuple(
                name
                for name in read_projection.dispatch_blocked_names
                if name not in names
            ),
        )
    dispatch = active.get(DEFERRED_TOOL_DISPATCH_CHAT_NAME)
    if isinstance(dispatch, ExecToolProjection):
        existing_hashes = dict(dispatch.authorized_definition_hashes)
        existing_hashes.update(authorized)
        retained_names = tuple(
            name for name in dispatch.authorized_names if name in names
        )
        active[DEFERRED_TOOL_DISPATCH_CHAT_NAME] = replace(
            dispatch,
            authorized_names=tuple(dict.fromkeys((*retained_names, *authorized))),
            authorized_definition_hashes=tuple(
                (name, definition_hash)
                for name, definition_hash in existing_hashes.items()
                if name in names
            ),
        )
    body[EXEC_PROJECTIONS_KEY] = active


def _selected_tool_name(tool_choice: Any) -> str | None:
    if not isinstance(tool_choice, dict):
        return None
    function = tool_choice.get("function")
    name = function.get("name") if isinstance(function, dict) else None
    if not isinstance(name, str):
        name = tool_choice.get("name")
    return name if isinstance(name, str) else None


def _canonical_hash(value: Any) -> str:
    serialized = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    ).encode()
    return f"sha256:{hashlib.sha256(serialized).hexdigest()}"


def _memory_key(principal_id: str, scope: dict[str, Any]) -> bytes:
    return hashlib.sha256(
        principal_id.encode() + b"\0" + _canonical_hash(scope).encode()
    ).digest()


def _now(value: datetime | None) -> datetime:
    current = value or datetime.now(timezone.utc)
    if current.tzinfo is None:
        current = current.replace(tzinfo=timezone.utc)
    return current.astimezone(timezone.utc)
