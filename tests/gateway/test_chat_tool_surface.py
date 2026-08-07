"""Tests for encrypted window-scoped final Chat tool-surface stability."""

from __future__ import annotations

import concurrent.futures
import sqlite3
import threading
from datetime import datetime, timedelta, timezone
from typing import Any

import pytest

from codex_rosetta.gateway.chat_tool_surface import (
    ChatToolSurfaceCoordinator,
    InMemoryChatToolSurfaceStore,
)
from codex_rosetta.gateway.code_mode_projection import (
    ExecToolProjection,
    plan_exec_tool_definitions,
)
from codex_rosetta.gateway.state_scope import GatewayStateScope
from codex_rosetta.gateway.tool_adaptation import (
    DEFERRED_CANDIDATES_KEY,
    EXEC_PROJECTIONS_KEY,
)
from codex_rosetta.observability.persistence import PersistenceManager
from codex_rosetta.observability.chat_tool_surface_store import (
    ChatToolSurfaceCapacityError,
    ChatToolSurfaceStore,
)
from codex_rosetta.observability.tool_mapping_crypto import (
    KEY_FILENAME,
    ToolMappingCipher,
    ToolMappingIntegrityError,
    ToolMappingKeyError,
)
from codex_rosetta.routing import ResolvedRoute


def _route(**overrides: Any) -> ResolvedRoute:
    values: dict[str, Any] = {
        "source_provider": "openai_responses",
        "target_provider": "openai_chat",
        "provider_name": "deepseek",
        "tool_profile_name": "builtin",
        "tool_profile": {},
    }
    values.update(overrides)
    return ResolvedRoute(**values)


def _scope(window: str = "window-a", principal: str = "principal-a"):
    return GatewayStateScope(
        principal_id=principal,
        provider_name="deepseek",
        model="deepseek-v4-flash",
        conversation_id=window,
        persistent=True,
    )


def _tool(name: str, *, field: str = "value") -> dict:
    return {
        "type": "function",
        "function": {
            "name": name,
            "description": f"Use {name}.",
            "parameters": {
                "type": "object",
                "properties": {field: {"type": "string"}},
                "additionalProperties": False,
            },
        },
    }


def _body(*tools: dict, projections: tuple[str, ...] = ()) -> dict:
    body = {"tools": list(tools), "messages": []}
    if projections:
        body[EXEC_PROJECTIONS_KEY] = {
            name: ExecToolProjection(
                item_id=f"dynamic.{name}",
                chat_name=name,
                nested_name=name,
                output_mode="mcp_content",
            )
            for name in projections
        }
    return body


def _apply(coordinator, body, *, scope=None, persistence=None, route=None):
    return coordinator.apply(
        body,
        route=route or _route(),
        state_scope=scope or _scope(),
        codex_window_id=(scope or _scope()).conversation_id,
        persistence=persistence,
    )


def test_reliable_added_and_changed_exec_tools_keep_first_ordered_surface():
    coordinator = ChatToolSurfaceCoordinator(InMemoryChatToolSurfaceStore())
    baseline = [_tool("exec"), _tool("request_plugin_install", field="plugin_id")]
    first = _apply(coordinator, _body(*baseline))
    assert first.profile["chat_tool_surface_decision"] == "created"

    changed = _tool("request_plugin_install", field="marketplace_id")
    added = _tool("list_available_plugins_to_install")
    second = _apply(
        coordinator,
        _body(
            baseline[0],
            changed,
            added,
            projections=(
                "request_plugin_install",
                "list_available_plugins_to_install",
            ),
        ),
    )

    assert second.body["tools"] == baseline
    assert second.profile["chat_tool_surface_decision"] == "locked"
    assert second.profile["chat_tool_surface_added"] == 1
    assert second.profile["chat_tool_surface_changed"] == 1
    assert second.profile["chat_tool_surface_deferred"] == 2


def test_exec_container_change_is_locked_only_when_exact_nested_sections_own_it():
    coordinator = ChatToolSurfaceCoordinator(InMemoryChatToolSurfaceStore())
    install = ExecToolProjection(
        item_id="function.request_plugin_install",
        chat_name="request_plugin_install",
        nested_name="request_plugin_install",
    )
    listing = ExecToolProjection(
        item_id="function.list_available_plugins_to_install",
        chat_name="list_available_plugins_to_install",
        nested_name="list_available_plugins_to_install",
    )
    projections = {
        "request_plugin_install": install,
        "list_available_plugins_to_install": listing,
    }
    old_description = """Exec prefix.

### `request_plugin_install`
Install one plugin.

exec tool declaration:
```ts
declare const tools: { request_plugin_install(args: { plugin_id: string }): Promise<unknown>; };
```

Exec suffix.
"""
    new_description = """Exec prefix.

### `request_plugin_install`
Install one plugin.

exec tool declaration:
```ts
declare const tools: { request_plugin_install(args: { plugin_id: string; suggest_reason: string }): Promise<unknown>; };
```

### `list_available_plugins_to_install`
List installable plugins.

exec tool declaration:
```ts
declare const tools: { list_available_plugins_to_install(args: {}): Promise<unknown>; };
```

Exec suffix.
"""
    old_plan = plan_exec_tool_definitions(old_description, projections)
    new_plan = plan_exec_tool_definitions(new_description, projections)
    old_exec = _tool("exec")
    old_exec["function"]["description"] = old_description
    new_exec = _tool("exec")
    new_exec["function"]["description"] = new_description
    baseline = [old_exec, old_plan.definitions["request_plugin_install"]]
    _apply(coordinator, _body(*baseline))

    body = _body(
        new_exec,
        new_plan.definitions["request_plugin_install"],
        new_plan.definitions["list_available_plugins_to_install"],
    )
    body[DEFERRED_CANDIDATES_KEY] = {
        name: {
            "projection": projections[name],
            "definition": new_plan.definitions[name],
            "definition_hash": f"sha256:{name}",
        }
        for name in projections
    }
    decision = _apply(coordinator, body)

    assert decision.body["tools"] == baseline
    assert decision.profile["chat_tool_surface_decision"] == "locked"
    assert decision.profile["chat_tool_surface_changed"] == 2
    assert decision.profile["chat_tool_surface_deferred"] == 2

    opaque_body = dict(body)
    opaque_body["tools"] = list(body["tools"])
    opaque_body["tools"][0] = _tool("exec")
    opaque_body["tools"][0]["function"]["description"] = (
        new_description + "Unknown trailing contract change.\n"
    )
    opaque_coordinator = ChatToolSurfaceCoordinator(InMemoryChatToolSurfaceStore())
    opaque = _apply(opaque_coordinator, _body(*baseline))
    assert opaque.profile["chat_tool_surface_decision"] == "created"
    rollover = _apply(opaque_coordinator, opaque_body)
    assert rollover.profile["chat_tool_surface_decision"] == "opaque_rollover"


def test_removed_tool_stays_visible_but_is_counted_stale():
    coordinator = ChatToolSurfaceCoordinator(InMemoryChatToolSurfaceStore())
    baseline = [_tool("exec"), _tool("temporary_tool")]
    _apply(coordinator, _body(*baseline))

    decision = _apply(coordinator, _body(baseline[0]))

    assert decision.body["tools"] == baseline
    assert decision.profile["chat_tool_surface_stale"] == 1


def test_locked_changed_direct_tool_enables_only_matching_live_nested_candidate():
    coordinator = ChatToolSurfaceCoordinator(InMemoryChatToolSurfaceStore())
    old = _tool("request_plugin_install", field="plugin_id")
    _apply(coordinator, _body(old))

    current = _tool("request_plugin_install", field="marketplace_id")
    body = _body(current)
    live_hash = "sha256:live"
    body[DEFERRED_CANDIDATES_KEY] = {
        "request_plugin_install": {
            "projection": ExecToolProjection(
                item_id="function.request_plugin_install",
                chat_name="request_plugin_install",
                nested_name="request_plugin_install",
            ),
            "definition": current,
            "definition_hash": live_hash,
            "authorized_definition_hash": live_hash,
        }
    }
    body[EXEC_PROJECTIONS_KEY] = {
        "tool_read": ExecToolProjection(
            item_id="injection.rosetta.tool_read",
            chat_name="tool_read",
            nested_name="exec",
            dispatch_blocked_names=("request_plugin_install",),
        ),
        "invoke_deferred_tool": ExecToolProjection(
            item_id="injection.rosetta.invoke_deferred_tool",
            chat_name="invoke_deferred_tool",
            nested_name="exec",
            input_mode="deferred_dispatch",
        ),
    }

    decision = _apply(coordinator, body)

    assert decision.body["tools"] == [old]
    projections = decision.body[EXEC_PROJECTIONS_KEY]
    assert "request_plugin_install" not in projections
    assert projections["tool_read"].dispatch_blocked_names == ()
    assert projections["invoke_deferred_tool"].authorized_names == (
        "request_plugin_install",
    )
    assert dict(projections["invoke_deferred_tool"].authorized_definition_hashes) == {
        "request_plugin_install": live_hash
    }


def test_mismatched_direct_and_nested_definitions_force_opaque_rollover():
    coordinator = ChatToolSurfaceCoordinator(InMemoryChatToolSurfaceStore())
    _apply(coordinator, _body(_tool("request_plugin_install", field="plugin_id")))
    current = _tool("request_plugin_install", field="marketplace_id")
    body = _body(current)
    body[DEFERRED_CANDIDATES_KEY] = {
        "request_plugin_install": {
            "projection": ExecToolProjection(
                item_id="function.request_plugin_install",
                chat_name="request_plugin_install",
                nested_name="request_plugin_install",
            ),
            "definition": _tool("request_plugin_install", field="guessed"),
            "definition_hash": "sha256:wrong",
        }
    }

    decision = _apply(coordinator, body)

    assert decision.profile["chat_tool_surface_decision"] == "opaque_rollover"


def test_opaque_or_explicitly_selected_change_rolls_epoch():
    coordinator = ChatToolSurfaceCoordinator(InMemoryChatToolSurfaceStore())
    _apply(coordinator, _body(_tool("exec")))

    opaque = _apply(coordinator, _body(_tool("exec"), _tool("unknown")))
    assert opaque.profile["chat_tool_surface_decision"] == "opaque_rollover"
    assert opaque.profile["chat_tool_surface_epoch"] == 1

    selected_body = _body(
        _tool("exec"),
        _tool("unknown"),
        _tool("request_plugin_install"),
        projections=("request_plugin_install",),
    )
    selected_body["tool_choice"] = {
        "type": "function",
        "function": {"name": "request_plugin_install"},
    }
    selected = _apply(coordinator, selected_body)
    assert selected.profile["chat_tool_surface_decision"] == "opaque_rollover"
    assert selected.profile["chat_tool_surface_rollover_reason"] == (
        "explicit_tool_choice"
    )


def test_window_and_principal_scopes_are_independent():
    coordinator = ChatToolSurfaceCoordinator(InMemoryChatToolSurfaceStore())
    first = _apply(coordinator, _body(_tool("one")), scope=_scope("window-a", "p1"))
    second = _apply(coordinator, _body(_tool("two")), scope=_scope("window-b", "p1"))
    third = _apply(coordinator, _body(_tool("three")), scope=_scope("window-a", "p2"))
    assert [
        item.profile["chat_tool_surface_decision"] for item in (first, second, third)
    ] == ["created", "created", "created"]


def test_non_eligible_routes_remain_stateless():
    coordinator = ChatToolSurfaceCoordinator(InMemoryChatToolSurfaceStore())
    body = _body(_tool("one"))
    decision = _apply(
        coordinator,
        body,
        route=_route(target_provider="anthropic"),
    )
    assert decision.body is body
    assert decision.profile == {}


def test_persistent_snapshot_survives_restart_without_plaintext_scope(tmp_path):
    coordinator = ChatToolSurfaceCoordinator(InMemoryChatToolSurfaceStore())
    baseline = _body(_tool("exec"))
    persistence = PersistenceManager(str(tmp_path))
    _apply(coordinator, baseline, persistence=persistence)
    database_bytes = persistence.db_path.read_bytes()
    assert b"window-a" not in database_bytes
    assert b"deepseek-v4-flash" not in database_bytes
    persistence.close()

    restarted = PersistenceManager(str(tmp_path))
    changed = _body(
        _tool("exec"),
        _tool("list_available_plugins_to_install"),
        projections=("list_available_plugins_to_install",),
    )
    decision = _apply(coordinator, changed, persistence=restarted)
    assert decision.body["tools"] == baseline["tools"]
    assert decision.profile["chat_tool_surface_decision"] == "locked"
    restarted.close()


def test_sliding_ttl_renews_and_expired_rows_are_cleaned(tmp_path):
    persistence = PersistenceManager(str(tmp_path))
    start = datetime(2026, 8, 1, tzinfo=timezone.utc)
    scope = {"window_id": "secret", "contract_generation": "g"}
    payload = {"epoch": 0, "tools": [_tool("one")]}
    persistence.load_or_create_chat_tool_surface(
        principal_id="p",
        scope=scope,
        initial_payload=payload,
        now=start,
    )
    persistence.load_or_create_chat_tool_surface(
        principal_id="p",
        scope=scope,
        initial_payload=payload,
        now=start + timedelta(hours=23),
    )
    assert (
        persistence.cleanup_expired_chat_tool_surfaces(start + timedelta(hours=25)) == 0
    )
    assert (
        persistence.cleanup_expired_chat_tool_surfaces(start + timedelta(hours=48)) == 1
    )
    persistence.close()


def test_ciphertext_tamper_fails_closed_on_restart(tmp_path):
    persistence = PersistenceManager(str(tmp_path))
    persistence.load_or_create_chat_tool_surface(
        principal_id="p",
        scope={"window_id": "secret", "contract_generation": "g"},
        initial_payload={"epoch": 0, "tools": [_tool("one")]},
    )
    persistence._conn.execute(  # noqa: SLF001 - intentional corruption test
        "UPDATE codex_chat_tool_surface_snapshots "
        "SET encrypted_payload = zeroblob(length(encrypted_payload))"
    )
    persistence._conn.commit()  # noqa: SLF001
    persistence.close()

    with pytest.raises(ToolMappingIntegrityError):
        PersistenceManager(str(tmp_path))


def test_wrong_key_fails_closed_on_restart(tmp_path):
    persistence = PersistenceManager(str(tmp_path))
    persistence.load_or_create_chat_tool_surface(
        principal_id="p",
        scope={"window_id": "secret", "contract_generation": "g"},
        initial_payload={"epoch": 0, "tools": [_tool("one")]},
    )
    persistence.close()
    (tmp_path / KEY_FILENAME).write_bytes(b"x" * 32)

    with pytest.raises(ToolMappingKeyError):
        PersistenceManager(str(tmp_path))


def test_capacity_failure_rolls_back_without_evicting_live_snapshot():
    connection = sqlite3.connect(":memory:", check_same_thread=False)
    cipher = ToolMappingCipher(b"k" * 32)
    store = ChatToolSurfaceStore(
        connection=connection,
        lock=threading.RLock(),
        cipher_loader=lambda _create: cipher,
        max_row_bytes=2_048,
        max_principal_rows=1,
        max_principal_bytes=4_096,
        max_global_rows=1,
        max_global_bytes=4_096,
    )
    store.load_or_create(
        principal_id="p",
        scope={"window_id": "one"},
        initial_payload={"epoch": 0, "tools": [_tool("one")]},
    )

    with pytest.raises(ChatToolSurfaceCapacityError):
        store.load_or_create(
            principal_id="p",
            scope={"window_id": "two"},
            initial_payload={"epoch": 0, "tools": [_tool("two")]},
        )

    assert store.count() == 1
    payload, created = store.load_or_create(
        principal_id="p",
        scope={"window_id": "one"},
        initial_payload={"epoch": 0, "tools": [_tool("replacement")]},
    )
    assert created is False
    assert payload["tools"] == [_tool("one")]
    connection.close()


def test_in_memory_first_writer_wins_under_concurrency():
    coordinator = ChatToolSurfaceCoordinator(InMemoryChatToolSurfaceStore())

    def run(name: str):
        return _apply(coordinator, _body(_tool(name), projections=(name,)))

    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as executor:
        decisions = list(executor.map(run, ("first", "second")))

    created = [
        decision
        for decision in decisions
        if decision.profile["chat_tool_surface_decision"] == "created"
    ]
    assert len(created) == 1
    final_surfaces = {str(decision.body["tools"]) for decision in decisions}
    assert len(final_surfaces) == 1
