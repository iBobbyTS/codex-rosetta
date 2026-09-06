"""Unit tests for Rosetta's private Codex Remote Compaction V2 coordinator."""

from __future__ import annotations

import asyncio
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from codex_rosetta._vendor.httpserver import JSONResponse, Response, StreamingResponse
from codex_rosetta.gateway import logging as gateway_logging
from codex_rosetta.gateway import proxy
from codex_rosetta.gateway.codex_compaction import (
    COMPACT_PROMPT,
    COMPACT_PROMPT_SHA256,
    SUMMARY_PREFIX,
    InvalidCodexCompactionRequest,
    InvalidCompactionSummary,
    build_compaction_response,
    create_compaction_mapping,
    extract_assistant_summary,
    prepare_codex_compaction,
)
from codex_rosetta.gateway.state_scope import GatewayStateScope
from codex_rosetta.gateway.logging import create_compaction_request_shape
from codex_rosetta.gateway.transport import UpstreamConnectionError, UpstreamResponse
from codex_rosetta.observability.persistence import PersistenceManager
from codex_rosetta.routing import ResolvedRoute


def _route(*, passthrough: bool = False) -> ResolvedRoute:
    return ResolvedRoute(
        source_provider="openai_responses",
        target_provider="openai_responses" if passthrough else "openai_chat",
        provider_name="test",
    )


def _request(reason: str = "context_limit") -> dict:
    return {
        "model": "deepseek-v4-flash",
        "input": [
            {"type": "message", "role": "user", "content": "history"},
            {"type": "compaction_trigger"},
        ],
        "tools": [{"type": "function", "name": "unwanted"}],
        "tool_choice": "required",
        "parallel_tool_calls": True,
        "additional_tools": [{"type": "computer"}],
        "client_metadata": {
            "x-codex-turn-metadata": json.dumps({"compaction": {"reason": reason}}),
            "keep": "this",
        },
    }


def _capture_gateway_logs(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    records: list[str] = []

    def capture(message: str, *args) -> None:
        records.append(message % args)

    monkeypatch.setattr(gateway_logging._logger, "info", capture)
    monkeypatch.setattr(gateway_logging._logger, "warning", capture)
    monkeypatch.setattr(gateway_logging._logger, "error", capture)
    return records


@pytest.mark.parametrize(
    ("passthrough", "reason", "expected"),
    [
        (True, "context_limit", "native"),
        (True, "user_requested", "native"),
        (True, "comp_hash_changed", "rosetta"),
        (True, "model_downshift", "rosetta"),
        (False, "context_limit", "rosetta"),
        (False, "user_requested", "rosetta"),
        (False, "comp_hash_changed", "rosetta"),
        (False, "model_downshift", "rosetta"),
    ],
)
def test_policy_uses_only_route_configuration_and_metadata_reason(
    passthrough: bool, reason: str, expected: str | None
) -> None:
    prepared = prepare_codex_compaction(
        _request(reason),
        route=_route(passthrough=passthrough),
        persistence=None,
        principal_id="client-a",
    )
    assert prepared.mode == expected
    if expected == "native":
        assert prepared.body == _request(reason)
        assert prepared.summary_request is None
    else:
        assert prepared.summary_request is not None


def test_openai_provider_transparently_passes_through_hash_change() -> None:
    body = _request("comp_hash_changed")
    prepared = prepare_codex_compaction(
        body,
        route=_route(passthrough=True),
        persistence=None,
        principal_id="client-a",
        provider_type="openai",
        force_rosetta_compaction=True,
    )

    assert prepared.mode == "native"
    assert prepared.body == body
    assert prepared.summary_request is None


@pytest.mark.parametrize(
    "reason", ["context_limit", "user_requested", "comp_hash_changed", "unknown"]
)
def test_forced_responses_policy_always_uses_rosetta(reason: str) -> None:
    prepared = prepare_codex_compaction(
        _request(reason),
        route=_route(passthrough=True),
        persistence=None,
        principal_id="client-a",
        force_rosetta_compaction=True,
    )

    assert prepared.mode == "rosetta"
    assert prepared.reason == reason
    assert prepared.summary_request is not None


def test_forced_policy_does_not_change_ordinary_requests_or_native_history() -> None:
    body = {
        "model": "gpt-5.6-terra",
        "input": [
            {"type": "compaction", "encrypted_content": "native-opaque"},
            {"type": "message", "role": "user", "content": "continue"},
        ],
    }

    prepared = prepare_codex_compaction(
        body,
        route=_route(passthrough=True),
        persistence=None,
        principal_id="client-a",
        force_rosetta_compaction=True,
    )

    assert prepared.mode is None
    assert prepared.body == body


def test_malformed_metadata_or_header_never_promotes_native_passthrough() -> None:
    body = _request()
    body["client_metadata"]["x-codex-turn-metadata"] = "not json"
    body["x-codex-turn-metadata"] = json.dumps(
        {"compaction": {"reason": "context_limit"}}
    )
    prepared = prepare_codex_compaction(
        body, route=_route(passthrough=True), persistence=None, principal_id="client-a"
    )
    assert prepared.reason == "unknown"
    assert prepared.mode == "rosetta"


@pytest.mark.parametrize(
    "input_items",
    [
        [{"type": "compaction_trigger"}, {"type": "message"}],
        [{"type": "compaction_trigger"}, {"type": "compaction_trigger"}],
    ],
)
def test_invalid_trigger_sequence_is_rejected(input_items: list[dict]) -> None:
    body = _request()
    body["input"] = input_items
    with pytest.raises(InvalidCodexCompactionRequest):
        prepare_codex_compaction(
            body, route=_route(), persistence=None, principal_id="client-a"
        )


def test_compaction_shape_buckets_non_string_item_types_as_unknown() -> None:
    shape = create_compaction_request_shape(
        {
            "model": "gpt-6-astra",
            "input": [{"type": ["not", "hashable"]}, {"type": None}],
        },
        stage="incoming",
        source_provider="openai_responses",
        target_provider="openai_chat",
        provider_name="test",
        stream=False,
    )
    assert shape.input_type_counts == (("unknown", 2),)


@pytest.mark.parametrize("stream", [False, True])
def test_invalid_trigger_warning_is_self_contained_and_prompt_free(
    monkeypatch: pytest.MonkeyPatch,
    stream: bool,
) -> None:
    records = _capture_gateway_logs(monkeypatch)
    body = _request("SECRET_REASON")
    body["parallel_tool_calls"] = "SECRET_INVALID_BOOLEAN"
    body["input"] = [
        {"type": "message", "content": "SECRET_PROMPT"},
        {"type": "SECRET_UNKNOWN_TYPE", "value": "SECRET_ITEM_VALUE"},
        {"type": "compaction_trigger"},
        {"type": "compaction_trigger"},
    ]
    handler = proxy.handle_streaming if stream else proxy.handle_non_streaming

    response, _ = asyncio.run(
        handler(
            _route(),
            MagicMock(force_rosetta_compaction=False),
            body,
            transport=MagicMock(),
            state_scope=GatewayStateScope.for_request(
                principal_id="client-a",
                provider_name="test",
                model="deepseek-v4-flash",
                window_id="thread-a:0",
            ),
        )
    )

    assert response.status_code == 400
    failures = [record for record in records if "[COMPACTION FAILURE]" in record]
    assert len(failures) == 1
    assert '"category":"invalid_request"' in failures[0]
    assert '"parallel_tool_calls":"invalid"' in failures[0]
    assert '"compaction_trigger":2' in failures[0]
    assert '"unknown":1' in failures[0]
    for secret in (
        "SECRET_REASON",
        "SECRET_INVALID_BOOLEAN",
        "SECRET_PROMPT",
        "SECRET_UNKNOWN_TYPE",
        "SECRET_ITEM_VALUE",
    ):
        assert secret not in "\n".join(records)


def test_preparation_failure_warning_does_not_log_exception_or_token(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    records = _capture_gateway_logs(monkeypatch)
    persistence = MagicMock()
    persistence.get_codex_compaction_mapping.side_effect = RuntimeError(
        "SECRET_PREPARATION_ERROR"
    )
    body = {
        "model": "gpt-6-astra",
        "input": [
            {
                "type": "compaction",
                "encrypted_content": "rskc_v1_SECRET_OPAQUE_TOKEN",
            }
        ],
    }

    with pytest.raises(RuntimeError, match="SECRET_PREPARATION_ERROR"):
        asyncio.run(
            proxy.handle_non_streaming(
                _route(passthrough=True),
                MagicMock(force_rosetta_compaction=False),
                body,
                transport=MagicMock(),
                persistence=persistence,
                state_scope=GatewayStateScope.for_request(
                    principal_id="client-a",
                    provider_name="test",
                    model="gpt-6-astra",
                    window_id="thread-a:0",
                ),
            )
        )

    failures = [record for record in records if "[COMPACTION FAILURE]" in record]
    assert len(failures) == 1
    assert '"category":"preparation"' in failures[0]
    assert '"replay_count":1' in failures[0]
    assert "SECRET_PREPARATION_ERROR" not in "\n".join(records)
    assert "SECRET_OPAQUE_TOKEN" not in "\n".join(records)


def test_rosetta_summary_request_strips_tools_and_preserves_other_fields() -> None:
    body = _request("comp_hash_changed")
    body["input"].insert(
        0,
        {
            "type": "additional_tools",
            "tools": [{"type": "function", "name": "lite-unwanted"}],
        },
    )
    body["custom_field"] = {"preserved": True}
    prepared = prepare_codex_compaction(
        body, route=_route(), persistence=None, principal_id="client-a"
    )
    assert prepared.summary_request is not None
    request = prepared.summary_request
    assert request["custom_field"] == {"preserved": True}
    assert request["stream"] is False
    assert all(
        key not in request
        for key in ("tools", "tool_choice", "parallel_tool_calls", "additional_tools")
    )
    assert all(item.get("type") != "additional_tools" for item in request["input"])
    assert request["client_metadata"] == {"keep": "this"}
    assert request["input"][-1]["content"][0]["text"] == COMPACT_PROMPT


def test_mapping_replays_only_for_its_principal_and_stores_prefixed_plaintext(
    tmp_path,
) -> None:
    persistence = PersistenceManager(str(tmp_path))
    created = create_compaction_mapping(
        persistence,
        principal_id="client-a",
        source_model="deepseek-v4-flash",
        reason="comp_hash_changed",
        summary="Orchid remains unchanged.",
        now=datetime(2026, 7, 1, tzinfo=timezone.utc),
    )
    row = persistence.get_codex_compaction_mapping(
        principal_id="client-a",
        token_hash=hashlib.sha256(created.token.encode()).hexdigest(),
        now="2026-07-02T00:00:00+00:00",
    )
    assert row is not None
    assert row["replacement_text"] == f"{SUMMARY_PREFIX}\n\nOrchid remains unchanged."
    assert row["prompt_sha256"] == COMPACT_PROMPT_SHA256

    request = {
        "model": "x",
        "input": [{"type": "compaction", "encrypted_content": created.token}],
    }
    restored = prepare_codex_compaction(
        request,
        route=_route(passthrough=True),
        persistence=persistence,
        principal_id="client-a",
        now=datetime(2026, 7, 2, tzinfo=timezone.utc),
    )
    assert restored.rehydrated_count == 1
    assert restored.body["input"][0]["content"][0]["text"] == row["replacement_text"]
    cross_principal = prepare_codex_compaction(
        request,
        route=_route(passthrough=True),
        persistence=persistence,
        principal_id="client-b",
        now=datetime(2026, 7, 2, tzinfo=timezone.utc),
    )
    assert cross_principal.body["input"] == []
    assert cross_principal.dropped_rosetta_count == 1
    persistence.close()


def test_non_rosetta_compaction_is_preserved_only_for_native_responses_route() -> None:
    request = {
        "model": "x",
        "input": [{"type": "compaction", "encrypted_content": "upstream"}],
    }
    assert (
        prepare_codex_compaction(
            request, route=_route(passthrough=True), persistence=None, principal_id="a"
        ).body["input"]
        == request["input"]
    )
    assert (
        prepare_codex_compaction(
            request, route=_route(), persistence=None, principal_id="a"
        ).body["input"]
        == []
    )


def test_summary_extraction_rejects_tools_and_empty_output() -> None:
    with pytest.raises(InvalidCompactionSummary):
        extract_assistant_summary({"output": [{"type": "function_call"}]})
    with pytest.raises(InvalidCompactionSummary):
        extract_assistant_summary(
            {"output": [{"type": "message", "role": "assistant", "content": []}]}
        )
    assert (
        extract_assistant_summary(
            {
                "output": [
                    {"type": "reasoning"},
                    {
                        "type": "message",
                        "role": "assistant",
                        "content": [{"type": "output_text", "text": "summary"}],
                    },
                ]
            }
        )
        == "summary"
    )


def test_canonical_non_stream_and_sse_lifecycle() -> None:
    token = "rskc_v1_test"
    response = build_compaction_response(model="model", token=token, stream=False)
    assert isinstance(response, Response)
    payload = json.loads(response.body)
    assert payload["output"] and payload["output"][0]["type"] == "compaction"
    assert payload["output"][0]["encrypted_content"] == token

    streamed = build_compaction_response(model="model", token=token, stream=True)
    assert isinstance(streamed, StreamingResponse)

    async def collect() -> list[str]:
        return [
            chunk if isinstance(chunk, str) else chunk.decode("utf-8")
            async for chunk in streamed._generator
        ]

    chunks = asyncio.run(collect())
    assert [chunk.split("\n", 1)[0] for chunk in chunks] == [
        "event: response.created",
        "event: response.output_item.added",
        "event: response.output_item.done",
        "event: response.completed",
    ]


def test_bundled_prompt_hash_is_stable() -> None:
    assert COMPACT_PROMPT_SHA256 == hashlib.sha256(COMPACT_PROMPT.encode()).hexdigest()


def test_internal_summary_retains_persistence_but_disables_body_logging(
    tmp_path, monkeypatch
) -> None:
    persistence = PersistenceManager(str(tmp_path))
    prepared = prepare_codex_compaction(
        _request("comp_hash_changed"),
        route=_route(),
        persistence=persistence,
        principal_id="client-a",
    )
    captured: dict = {}

    async def fake_handle_non_streaming(*args, **kwargs):
        captured.update(kwargs)
        return (
            JSONResponse(
                {
                    "output": [
                        {
                            "type": "message",
                            "role": "assistant",
                            "content": [{"type": "output_text", "text": "summary"}],
                        }
                    ]
                }
            ),
            {},
        )

    monkeypatch.setattr(proxy, "handle_non_streaming", fake_handle_non_streaming)
    response, _ = asyncio.run(
        proxy._run_rosetta_compaction(
            route=_route(),
            provider_info=MagicMock(),
            preparation=prepared,
            transport=MagicMock(),
            metadata_store=None,
            codex_tool_store=None,
            extra_headers=None,
            persistence=persistence,
            state_scope=GatewayStateScope.for_request(
                principal_id="client-a",
                provider_name="test",
                model="deepseek-v4-flash",
                window_id="thread-a:0",
            ),
            codex_window_id="thread-a:0",
            image_fetch_workers=None,
            stream=False,
            model_group_failover=True,
        )
    )

    assert response.status_code == 200
    assert captured["persistence"] is persistence
    assert captured["body_log_state"] is None
    assert captured["upstream_error_log_state"] is None
    assert captured["skip_codex_compaction"] is True
    assert captured["model_group_failover"] is True
    assert persistence.count_codex_compaction_mappings() == 1
    persistence.close()


@pytest.mark.parametrize("stream", [False, True])
@pytest.mark.parametrize(
    ("status_code", "synthetic", "expected_origin"),
    [
        (201, False, "upstream_response"),
        (204, False, "upstream_response"),
        (302, False, "upstream_response"),
        (500, False, "upstream_response"),
        (503, True, "transport_exhaustion"),
    ],
)
def test_compaction_summary_failure_promotes_model_group_rotation_marker(
    tmp_path,
    stream: bool,
    status_code: int,
    synthetic: bool,
    expected_origin: str,
) -> None:
    persistence = PersistenceManager(str(tmp_path))
    transport = MagicMock()
    raw_content = (
        b"" if status_code == 204 else b'{"error":{"message":"summary failed"}}'
    )
    transport.send_request = AsyncMock(
        return_value=UpstreamResponse(
            status_code=status_code,
            body=None,
            raw_content=raw_content,
            synthetic=synthetic,
        )
    )
    handler = proxy.handle_streaming if stream else proxy.handle_non_streaming

    response, profile = asyncio.run(
        handler(
            _route(),
            MagicMock(force_rosetta_compaction=False),
            _request("context_limit"),
            transport=transport,
            persistence=persistence,
            state_scope=GatewayStateScope.for_request(
                principal_id="client-a",
                provider_name="test",
                model="deepseek-v4-flash",
                window_id="thread-a:0",
            ),
            model_group_failover=True,
        )
    )

    assert response.status_code == status_code
    assert not isinstance(response, StreamingResponse)
    assert json.loads(response.body) == {
        "error": {
            "message": (
                "Upstream: HTTP 204 error response did not include a message"
                if status_code == 204
                else "Upstream: summary failed"
            )
        }
    }
    assert transport.send_request.await_count == 1
    call = transport.send_request.await_args
    assert call is not None
    assert call.kwargs["retry_nonstandard_statuses"] is True
    assert profile["upstream_provider_failure"] is True
    assert profile["provider_failure_origin"] == expected_origin
    assert profile["compaction_summary_upstream_provider_failure"] is True
    assert profile["compaction_summary_provider_failure_origin"] == expected_origin
    persistence.close()


@pytest.mark.parametrize("stream", [False, True])
def test_summary_http_failure_uses_safe_warning_and_distinct_summary_shape(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
    stream: bool,
) -> None:
    records = _capture_gateway_logs(monkeypatch)
    persistence = PersistenceManager(str(tmp_path))
    transport = MagicMock()
    transport.send_request = AsyncMock(
        return_value=UpstreamResponse(
            status_code=400,
            body=None,
            raw_content=b'{"error":{"message":"SECRET_UPSTREAM_ERROR"}}',
        )
    )
    body = _request("SECRET_REASON")
    body["parallel_tool_calls"] = False
    body["input"].insert(
        1,
        {"type": "SECRET_UNKNOWN_TYPE", "encrypted_content": "SECRET_TOKEN"},
    )
    handler = proxy.handle_streaming if stream else proxy.handle_non_streaming

    response, _ = asyncio.run(
        handler(
            _route(),
            MagicMock(force_rosetta_compaction=False),
            body,
            transport=transport,
            persistence=persistence,
            state_scope=GatewayStateScope.for_request(
                principal_id="client-a",
                provider_name="test",
                model="deepseek-v4-flash",
                window_id="thread-a:0",
            ),
        )
    )

    assert response.status_code == 400
    failures = [record for record in records if "[COMPACTION FAILURE]" in record]
    assert len(failures) == 1
    assert '"category":"summary_http"' in failures[0]
    assert '"parallel_tool_calls":"false"' in failures[0]
    assert '"summary_shape"' in failures[0]
    assert '"parallel_tool_calls":"absent"' in failures[0]
    assert '"stage":"summary"' in failures[0]
    assert not [record for record in records if "[UPSTREAM ERROR]" in record]
    for secret in (
        "SECRET_UPSTREAM_ERROR",
        "SECRET_REASON",
        "SECRET_UNKNOWN_TYPE",
        "SECRET_TOKEN",
    ):
        assert secret not in "\n".join(records)
    persistence.close()


@pytest.mark.parametrize("stream", [False, True])
@pytest.mark.parametrize(
    ("failure_kind", "expected_category"),
    [("http", "native_http"), ("transport", "native_transport")],
)
def test_native_failure_uses_safe_warning_without_generic_raw_error(
    monkeypatch: pytest.MonkeyPatch,
    stream: bool,
    failure_kind: str,
    expected_category: str,
) -> None:
    records = _capture_gateway_logs(monkeypatch)
    transport = MagicMock()
    if failure_kind == "transport":
        failure = UpstreamConnectionError("SECRET_TRANSPORT_ERROR")
        if stream:
            transport.send_streaming = AsyncMock(side_effect=failure)
        else:
            transport.send_request = AsyncMock(side_effect=failure)
    elif stream:
        upstream_stream = MagicMock(status_code=400)
        upstream_stream.read_error = AsyncMock(return_value="SECRET_HTTP_ERROR")
        upstream_stream.close = AsyncMock()
        transport.send_streaming = AsyncMock(return_value=upstream_stream)
    else:
        transport.send_request = AsyncMock(
            return_value=UpstreamResponse(
                status_code=400,
                body=None,
                raw_content=b'{"error":{"message":"SECRET_HTTP_ERROR"}}',
            )
        )
    body = _request("context_limit")
    body["parallel_tool_calls"] = False
    body["stream"] = stream
    handler = proxy.handle_streaming if stream else proxy.handle_non_streaming

    response, _ = asyncio.run(
        handler(
            _route(passthrough=True),
            MagicMock(force_rosetta_compaction=False, request_encoding="identity"),
            body,
            transport=transport,
            state_scope=GatewayStateScope.for_request(
                principal_id="client-a",
                provider_name="test",
                model="deepseek-v4-flash",
                window_id="thread-a:0",
            ),
        )
    )

    assert response.status_code in {400, 502}
    failures = [record for record in records if "[COMPACTION FAILURE]" in record]
    assert len(failures) == 1
    assert f'"category":"{expected_category}"' in failures[0]
    assert '"parallel_tool_calls":"false"' in failures[0]
    assert f'"stream":"{str(stream).lower()}"' in failures[0]
    assert not [record for record in records if "[UPSTREAM ERROR]" in record]
    assert "SECRET_HTTP_ERROR" not in "\n".join(records)
    assert "SECRET_TRANSPORT_ERROR" not in "\n".join(records)


def test_summary_transport_failure_uses_safe_warning(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    records = _capture_gateway_logs(monkeypatch)
    persistence = PersistenceManager(str(tmp_path))
    transport = MagicMock()
    transport.send_request = AsyncMock(
        side_effect=UpstreamConnectionError("SECRET_SUMMARY_TRANSPORT_ERROR")
    )
    body = _request()
    body["parallel_tool_calls"] = False

    response, _ = asyncio.run(
        proxy.handle_non_streaming(
            _route(),
            MagicMock(force_rosetta_compaction=False),
            body,
            transport=transport,
            persistence=persistence,
            state_scope=GatewayStateScope.for_request(
                principal_id="client-a",
                provider_name="test",
                model="deepseek-v4-flash",
                window_id="thread-a:0",
            ),
        )
    )

    assert response.status_code == 502
    failures = [record for record in records if "[COMPACTION FAILURE]" in record]
    assert len(failures) == 1
    assert '"category":"summary_transport"' in failures[0]
    assert '"summary_shape"' in failures[0]
    assert "SECRET_SUMMARY_TRANSPORT_ERROR" not in "\n".join(records)
    persistence.close()


@pytest.mark.parametrize(
    ("failure_kind", "expected_category", "expected_status"),
    [("parse", "summary_parse", 502), ("persistence", "persistence", 503)],
)
def test_summary_post_response_failures_use_safe_warning(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
    failure_kind: str,
    expected_category: str,
    expected_status: int,
) -> None:
    records = _capture_gateway_logs(monkeypatch)
    persistence = PersistenceManager(str(tmp_path))
    prepared = prepare_codex_compaction(
        _request("comp_hash_changed"),
        route=_route(),
        persistence=persistence,
        principal_id="client-a",
    )

    async def summary_handler(*args, **kwargs):
        del args, kwargs
        if failure_kind == "parse":
            return (
                JSONResponse(
                    {
                        "output": [
                            {
                                "type": "function_call",
                                "name": "SECRET_SUMMARY_PAYLOAD",
                            }
                        ]
                    }
                ),
                {},
            )
        return (
            JSONResponse(
                {
                    "output": [
                        {
                            "type": "message",
                            "role": "assistant",
                            "content": [
                                {"type": "output_text", "text": "safe summary"}
                            ],
                        }
                    ]
                }
            ),
            {},
        )

    monkeypatch.setattr(proxy, "handle_non_streaming", summary_handler)
    if failure_kind == "persistence":
        monkeypatch.setattr(
            proxy,
            "create_compaction_mapping",
            MagicMock(side_effect=RuntimeError("SECRET_PERSISTENCE_ERROR")),
        )

    response, _ = asyncio.run(
        proxy._run_rosetta_compaction(
            route=_route(),
            provider_info=MagicMock(force_rosetta_compaction=False),
            preparation=prepared,
            transport=MagicMock(),
            metadata_store=None,
            codex_tool_store=None,
            extra_headers=None,
            persistence=persistence,
            state_scope=GatewayStateScope.for_request(
                principal_id="client-a",
                provider_name="test",
                model="deepseek-v4-flash",
                window_id="thread-a:0",
            ),
            codex_window_id="thread-a:0",
            image_fetch_workers=None,
            stream=False,
        )
    )

    assert response.status_code == expected_status
    failures = [record for record in records if "[COMPACTION FAILURE]" in record]
    assert len(failures) == 1
    assert f'"category":"{expected_category}"' in failures[0]
    assert '"summary_shape"' in failures[0]
    assert "SECRET_SUMMARY_PAYLOAD" not in "\n".join(records)
    assert "SECRET_PERSISTENCE_ERROR" not in "\n".join(records)
    persistence.close()


@pytest.mark.parametrize("stream", [False, True])
def test_missing_persistence_returns_exact_503_before_summary_call(
    monkeypatch, stream: bool
) -> None:
    records = _capture_gateway_logs(monkeypatch)
    prepared = prepare_codex_compaction(
        _request("user_requested"),
        route=_route(passthrough=True),
        persistence=None,
        principal_id="client-a",
        force_rosetta_compaction=True,
    )
    summary_handler = MagicMock()
    monkeypatch.setattr(proxy, "handle_non_streaming", summary_handler)
    provider_info = MagicMock(force_rosetta_compaction=True)
    transport = MagicMock()

    response, profile = asyncio.run(
        proxy._run_rosetta_compaction(
            route=_route(passthrough=True),
            provider_info=provider_info,
            preparation=prepared,
            transport=transport,
            metadata_store=None,
            codex_tool_store=None,
            extra_headers=None,
            persistence=None,
            state_scope=GatewayStateScope.for_request(
                principal_id="client-a",
                provider_name="test",
                model="deepseek-v4-flash",
                window_id="thread-a:0",
            ),
            codex_window_id="thread-a:0",
            image_fetch_workers=None,
            stream=stream,
        )
    )

    assert response.status_code == 503
    assert isinstance(response, Response)
    assert "Codex Rosetta: SQLite is not available for prompt compaction" in (
        response.body.decode("utf-8")
    )
    assert profile["compaction_forced_rosetta"] is True
    summary_handler.assert_not_called()
    assert transport.mock_calls == []
    failures = [record for record in records if "[COMPACTION FAILURE]" in record]
    assert len(failures) == 1
    assert '"category":"summary_persistence_unavailable"' in failures[0]
    assert '"summary_shape"' in failures[0]


def test_live_quality_matrix_uses_identical_input_and_optional_gpt_provider() -> None:
    live_root = Path(__file__).parents[2] / "tests" / "live_agent"
    quality = live_root / "context_compaction_summary_quality"

    assert (quality / "01" / "TASK.md").read_bytes() == (
        quality / "02" / "TASK.md"
    ).read_bytes()
    assert (quality / "01" / "scenario.py").read_bytes() == (
        quality / "02" / "scenario.py"
    ).read_bytes()
    assert (quality / "01" / "QUERY.md").read_bytes() == (
        quality / "02" / "QUERY.md"
    ).read_bytes()

    gpt = json.loads((quality / "01" / "expected.json").read_text())
    deepseek = json.loads((quality / "02" / "expected.json").read_text())
    assert gpt["gateway_provider"] is None
    assert gpt["default_model"] == "gpt-5.6-terra"
    assert deepseek["default_model"] == "deepseek-v4-flash"
    assert gpt["model_auto_compact_token_limit"] == 15000
    assert deepseek["model_auto_compact_token_limit"] == 15000
    assert gpt["expected_compaction_count"] == 1
    assert deepseek["expected_compaction_count"] == 1
    assert gpt["phase1_marker"] == "PHASE1:QUALITY_CONTEXT_READY"
    assert deepseek["phase1_marker"] == gpt["phase1_marker"]
    assert gpt["resume_prompt_file"] == "QUERY.md"
    assert deepseek["resume_prompt_file"] == "QUERY.md"
    assert gpt["resume_auto_compact_token_limit"] == 1_000_000
    assert deepseek["resume_auto_compact_token_limit"] == 1_000_000
    assert gpt["expected_resume_compaction_count"] == 0
    assert deepseek["expected_resume_compaction_count"] == 0

    facts = json.loads((quality / "expected_facts.json").read_text())
    assert set(facts) == {
        "project",
        "completed_stage",
        "immutable_file",
        "timezone",
        "active_endpoint",
        "superseded_endpoint",
        "predeploy_gate",
        "reference_code",
        "rollout_strategy",
        "strategy_reason",
        "deployment_owner",
    }
    model_prompts = (quality / "01" / "TASK.md").read_text() + (
        quality / "01" / "QUERY.md"
    ).read_text()
    for value in facts.values():
        if isinstance(value, str):
            assert value not in model_prompts


def test_protocol_context_limit_cells_use_identical_non_quality_fixture() -> None:
    suite = Path(__file__).parents[2] / "tests" / "live_agent" / "context_compaction"
    assert (suite / "01" / "TASK.md").read_bytes() == (
        suite / "02" / "TASK.md"
    ).read_bytes()
    assert (suite / "01" / "scenario.py").read_bytes() == (
        suite / "02" / "scenario.py"
    ).read_bytes()

    assert (suite / "01" / "scenario.py").read_bytes() == (
        suite / "05" / "scenario.py"
    ).read_bytes()
    protocol = json.loads((suite / "01" / "expected.json").read_text())
    exactly_once = json.loads((suite / "05" / "expected.json").read_text())
    assert protocol["target_scope"] == "remote_compaction_protocol"
    assert exactly_once["target_scope"] == "post_compaction_exactly_once"
    assert (suite / "01" / "TASK.md").read_bytes() != (
        suite / "05" / "TASK.md"
    ).read_bytes()
