"""OR-S01.1-CONTROL-WIRE: pure DeepSeek request/control contract tests."""

from __future__ import annotations

import ast
import asyncio
import builtins
import importlib.util
import inspect
import json
import os
import random
import shutil
import stat
import subprocess
import sys
import tempfile
import tomllib
import zipfile
from collections.abc import Callable
from pathlib import Path
from typing import Any, Never, cast

import pytest

import codex_rosetta.gateway.deepseek_responses_search as deepseek_search
from codex_rosetta.gateway.deepseek_responses_search import (
    DEEPSEEK_RESPONSES_OFFICIAL_ORIGIN,
    DEEPSEEK_RESPONSES_SEARCH_MODEL,
    DEEPSEEK_RESPONSES_SEARCH_RESPONSE_MAX_BYTES,
    DeepSeekResponsesSearchCredentialCollisionError,
    DeepSeekResponsesSearchParseError,
    DeepSeekResponsesSearchRequest,
    build_deepseek_responses_search_request,
    normalize_deepseek_responses_origin,
    parse_deepseek_responses_search_response,
    publish_deepseek_responses_search_response,
)
from codex_rosetta.gateway.transport.http.transport import BoundedHttpResponse
from codex_rosetta._vendor.httpclient import HttpTimeoutError
from codex_rosetta.observability.redaction import SecretRedactor

_EVIDENCE_PATH = Path(__file__).parents[2] / "scripts" / "deepseek_search_evidence.py"
_EVIDENCE_SPEC = importlib.util.spec_from_file_location(
    "deepseek_search_evidence", _EVIDENCE_PATH
)
assert _EVIDENCE_SPEC is not None and _EVIDENCE_SPEC.loader is not None
_EVIDENCE_MODULE = importlib.util.module_from_spec(_EVIDENCE_SPEC)
_EVIDENCE_SPEC.loader.exec_module(_EVIDENCE_MODULE)
DeepSeekEvidencePreparationError = _EVIDENCE_MODULE.DeepSeekEvidencePreparationError
DeepSeekEvidencePublicationError = _EVIDENCE_MODULE.DeepSeekEvidencePublicationError
PreparedEvidencePublication = _EVIDENCE_MODULE.PreparedEvidencePublication
prepare_evidence_publication = _EVIDENCE_MODULE.prepare_evidence_publication
serialize_evidence_manifest = _EVIDENCE_MODULE.serialize_evidence_manifest
write_private_evidence_bytes = _EVIDENCE_MODULE.write_private_evidence_bytes

_PURE_ORIGIN_PATH = Path(__file__).parents[2] / "scripts" / "deepseek_search_origin.py"

_SMOKE_MODULE_PATH = (
    Path(__file__).parents[2] / "scripts" / "deepseek_web_search_smoke.py"
)
_SMOKE_SPEC = importlib.util.spec_from_file_location(
    "deepseek_web_search_smoke", _SMOKE_MODULE_PATH
)
assert _SMOKE_SPEC is not None and _SMOKE_SPEC.loader is not None
_SMOKE_MODULE = importlib.util.module_from_spec(_SMOKE_SPEC)
_SMOKE_SPEC.loader.exec_module(_SMOKE_MODULE)
CallAdmission = _SMOKE_MODULE.CallAdmission
DeepSeekOfflineHarnessError = _SMOKE_MODULE.DeepSeekOfflineHarnessError
DeepSeekSmokeCallAdmissionError = _SMOKE_MODULE.DeepSeekSmokeCallAdmissionError
DeepSeekSmokeQualificationError = _SMOKE_MODULE.DeepSeekSmokeQualificationError
QualifiedDeepSeekProvider = _SMOKE_MODULE.QualifiedDeepSeekProvider
qualify_deepseek_provider = _SMOKE_MODULE.qualify_deepseek_provider
run_offline_deepseek_search_harness = _SMOKE_MODULE.run_offline_deepseek_search_harness


def _load_pure_origin_module():
    spec = importlib.util.spec_from_file_location(
        "deepseek_search_origin_test", _PURE_ORIGIN_PATH
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


_EXPECTED_PROMPT = (
    "Search the web for the following query. Return a concise factual answer and "
    "cite the sources you used.\n\nQuery: current release notes"
)
_VALID_REQUEST = {
    "query": "current release notes",
    "origin": DEEPSEEK_RESPONSES_OFFICIAL_ORIGIN,
    "model": DEEPSEEK_RESPONSES_SEARCH_MODEL,
    "max_output_tokens": 1024,
    "citation_limit": 5,
    "timeout": 30,
}


def _build_request(**overrides: object) -> DeepSeekResponsesSearchRequest:
    values = {**_VALID_REQUEST, **overrides}
    return build_deepseek_responses_search_request(**values)


def _direct_request(**overrides: object) -> DeepSeekResponsesSearchRequest:
    values = {**_VALID_REQUEST, **overrides}
    return DeepSeekResponsesSearchRequest(**cast(Any, values))


@pytest.mark.parametrize("max_output_tokens", [512, 1024, 1536])
def test_request_body_is_exact_for_each_approved_integer_token_limit(
    max_output_tokens: int,
) -> None:
    request = _build_request(max_output_tokens=max_output_tokens)

    assert request.body == {
        "model": "deepseek-v4-flash",
        "input": _EXPECTED_PROMPT,
        "tools": [{"type": "web_search"}],
        "tool_choice": {"type": "web_search"},
        "max_output_tokens": max_output_tokens,
    }
    assert type(request.body["max_output_tokens"]) is int
    assert set(request.body) == {
        "model",
        "input",
        "tools",
        "tool_choice",
        "max_output_tokens",
    }


def test_request_body_excludes_every_local_or_forbidden_field() -> None:
    request = _build_request(citation_limit=8, timeout=2.5)

    forbidden = {
        "citation_limit",
        "timeout",
        "origin",
        "domains",
        "settings",
        "principal_id",
        "window_id",
        "previous_response_id",
        "conversation",
        "metadata",
        "include",
        "store",
        "cache_key",
    }
    assert forbidden.isdisjoint(request.body)
    assert request.citation_limit == 8
    assert request.timeout == 2.5
    assert request.origin == DEEPSEEK_RESPONSES_OFFICIAL_ORIGIN


def test_request_body_is_fresh_and_cannot_mutate_validated_request() -> None:
    request = _build_request()
    first = request.body
    first["model"] = "changed"
    tools = first["tools"]
    assert isinstance(tools, list)
    cast(list[object], tools).append({"type": "unsupported"})

    assert request.body == {
        "model": "deepseek-v4-flash",
        "input": _EXPECTED_PROMPT,
        "tools": [{"type": "web_search"}],
        "tool_choice": {"type": "web_search"},
        "max_output_tokens": 1024,
    }


def test_request_value_cannot_bypass_validation_by_direct_construction() -> None:
    with pytest.raises(ValueError, match="max_output_tokens"):
        DeepSeekResponsesSearchRequest(
            origin=DEEPSEEK_RESPONSES_OFFICIAL_ORIGIN,
            model=DEEPSEEK_RESPONSES_SEARCH_MODEL,
            query="query",
            max_output_tokens=True,
            citation_limit=5,
            timeout=30,
        )


class _IntSubclass(int):
    pass


class _HookedStr(str):
    hooks: list[str]

    def __new__(cls, value: str, hooks: list[str]) -> _HookedStr:
        instance = str.__new__(cls, value)
        instance.hooks = hooks
        return instance

    def _fail(self, hook: str) -> Never:
        self.hooks.append(hook)
        raise RuntimeError("caller-controlled-text")

    def strip(self, chars: str | None = None, /) -> str:
        self._fail("strip")

    def __len__(self) -> int:
        self._fail("len")

    def __ne__(self, other: object) -> bool:
        del other
        self._fail("ne")

    def __format__(self, format_spec: str) -> str:
        del format_spec
        self._fail("format")


class _SpoofingStr(str):
    hooks: list[str]

    def __new__(cls, value: str, hooks: list[str]) -> _SpoofingStr:
        instance = str.__new__(cls, value)
        instance.hooks = hooks
        return instance

    def strip(self, chars: str | None = None, /) -> str:
        del chars
        self.hooks.append("strip")
        return self

    def __len__(self) -> int:
        self.hooks.append("len")
        return 1

    def __ne__(self, other: object) -> bool:
        del other
        self.hooks.append("ne")
        return False

    def __format__(self, format_spec: str) -> str:
        del format_spec
        self.hooks.append("format")
        return "rewritten-by-caller"


class _HookedInt(int):
    hooks: list[str]

    def __new__(cls, value: int, hooks: list[str]) -> _HookedInt:
        instance = int.__new__(cls, value)
        instance.hooks = hooks
        return instance

    def __float__(self) -> float:
        self.hooks.append("float")
        raise RuntimeError("caller-controlled-text")


class _HookedFloat(float):
    hooks: list[str]

    def __new__(cls, value: float, hooks: list[str]) -> _HookedFloat:
        instance = float.__new__(cls, value)
        instance.hooks = hooks
        return instance

    def __float__(self) -> float:
        self.hooks.append("float")
        raise RuntimeError("caller-controlled-text")


@pytest.mark.parametrize("factory", [_build_request, _direct_request])
@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        (
            "origin",
            "https://api.deepseek.com",
            "DeepSeek Responses origin must be the official HTTPS root",
        ),
        (
            "model",
            "deepseek-v4-pro",
            "DeepSeek Responses search model is not supported",
        ),
        (
            "query",
            "x" * 4001,
            "DeepSeek Responses search query must be a string",
        ),
    ],
)
def test_string_subclass_hooks_cannot_escape_or_run(
    factory: Callable[..., DeepSeekResponsesSearchRequest],
    field: str,
    value: str,
    message: str,
) -> None:
    hooks: list[str] = []
    invalid = _HookedStr(value, hooks)

    with pytest.raises(ValueError) as caught:
        factory(**{field: invalid})

    assert str(caught.value) == message
    assert hooks == []


@pytest.mark.parametrize("factory", [_build_request, _direct_request])
@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("model", "deepseek-v4-pro"),
        ("query", "x" * 4001),
        ("query", "query whose formatting must stay fixed"),
    ],
)
def test_string_subclass_cannot_spoof_model_query_or_prompt(
    factory: Callable[..., DeepSeekResponsesSearchRequest], field: str, value: str
) -> None:
    hooks: list[str] = []
    invalid = _SpoofingStr(value, hooks)

    with pytest.raises(ValueError) as caught:
        request = factory(**{field: invalid})
        request.body

    assert len(str(caught.value)) <= 80
    assert "rewritten-by-caller" not in str(caught.value)
    assert hooks == []


@pytest.mark.parametrize("factory", [_build_request, _direct_request])
@pytest.mark.parametrize("subclass", [_HookedInt, _HookedFloat])
def test_numeric_subclass_timeout_hook_cannot_escape_or_run(
    factory: Callable[..., DeepSeekResponsesSearchRequest],
    subclass: Callable[[int, list[str]], int | float],
) -> None:
    hooks: list[str] = []
    invalid = subclass(30, hooks)

    with pytest.raises(ValueError) as caught:
        factory(timeout=invalid)

    assert str(caught.value) == (
        "DeepSeek Responses timeout must be a finite positive number"
    )
    assert hooks == []


@pytest.mark.parametrize(
    ("field", "value"),
    [("max_output_tokens", 1024), ("citation_limit", 5)],
)
def test_integer_subclass_control_hook_cannot_run(field: str, value: int) -> None:
    hooks: list[str] = []
    invalid = _HookedInt(value, hooks)

    with pytest.raises(ValueError):
        _build_request(**{field: invalid})

    assert hooks == []


def test_persisted_values_are_exact_builtin_canonical_scalars() -> None:
    request = _build_request(
        origin="HTTPS://API.DEEPSEEK.COM:443/",
        query="  current release notes  ",
        timeout=30,
    )

    assert request.origin == DEEPSEEK_RESPONSES_OFFICIAL_ORIGIN
    assert request.model == DEEPSEEK_RESPONSES_SEARCH_MODEL
    assert request.query == "current release notes"
    assert request.timeout == 30.0
    assert type(request.origin) is str
    assert type(request.model) is str
    assert type(request.query) is str
    assert type(request.timeout) is float


@pytest.mark.parametrize(
    "invalid",
    [
        True,
        False,
        512.0,
        1024.0,
        1536.0,
        "1024",
        None,
        0,
        511,
        513,
        2048,
        _IntSubclass(512),
    ],
)
def test_control_rejects_non_exact_or_unapproved_token_limits(invalid: object) -> None:
    with pytest.raises(ValueError, match="max_output_tokens"):
        _build_request(max_output_tokens=invalid)


@pytest.mark.parametrize("citation_limit", [1, 2, 5, 8])
def test_control_accepts_exact_integer_citation_limits(citation_limit: int) -> None:
    request = _build_request(citation_limit=citation_limit)

    assert request.citation_limit == citation_limit
    assert "citation_limit" not in request.body


@pytest.mark.parametrize(
    "invalid", [True, False, 1.0, 8.0, "5", None, 0, -1, 9, _IntSubclass(1)]
)
def test_control_rejects_non_exact_or_out_of_range_citation_limits(
    invalid: object,
) -> None:
    with pytest.raises(ValueError, match="citation_limit"):
        _build_request(citation_limit=invalid)


@pytest.mark.parametrize(
    ("timeout", "normalized"), [(1, 1.0), (0.125, 0.125), (30, 30.0)]
)
def test_control_normalizes_finite_positive_timeout(
    timeout: int | float, normalized: float
) -> None:
    request = _build_request(timeout=timeout)

    assert request.timeout == normalized
    assert type(request.timeout) is float
    assert "timeout" not in request.body


@pytest.mark.parametrize(
    "invalid",
    [
        True,
        False,
        None,
        "30",
        0,
        -1,
        -0.5,
        float("nan"),
        float("inf"),
        float("-inf"),
        pytest.param(10**10000, id="overflow-int"),
    ],
)
def test_control_rejects_non_finite_non_positive_or_non_numeric_timeout(
    invalid: object,
) -> None:
    with pytest.raises(ValueError, match="finite positive number"):
        _build_request(timeout=invalid)


def test_pre_io_control_validation_does_not_coerce_arbitrary_objects() -> None:
    coerced = False

    class NumberLike:
        def __float__(self) -> float:
            nonlocal coerced
            coerced = True
            return 30.0

    with pytest.raises(ValueError, match="finite positive number"):
        _build_request(timeout=NumberLike())

    assert coerced is False


def test_request_query_is_trimmed_once_and_uses_fixed_prompt() -> None:
    request = _build_request(query=" \tcurrent release notes\n")

    assert request.query == "current release notes"
    assert request.body["input"] == _EXPECTED_PROMPT


@pytest.mark.parametrize(
    "query",
    [pytest.param("x", id="min-length"), pytest.param("x" * 4000, id="max-length")],
)
def test_request_accepts_query_length_boundaries(query: str) -> None:
    request = _build_request(query=query)

    assert request.query == query
    assert request.body["input"] == (
        "Search the web for the following query. Return a concise factual answer "
        f"and cite the sources you used.\n\nQuery: {query}"
    )


@pytest.mark.parametrize(
    "invalid", [None, 1, True, "", " \t\n", pytest.param("x" * 4001, id="too-long")]
)
def test_request_rejects_invalid_query_without_echo(invalid: object) -> None:
    with pytest.raises(ValueError) as caught:
        _build_request(query=invalid)

    assert len(str(caught.value)) <= 80
    if isinstance(invalid, str) and invalid:
        assert invalid not in str(caught.value)


@pytest.mark.parametrize(
    "invalid",
    [None, True, "", "deepseek-v4-pro", " deepseek-v4-flash", "DEEPSEEK-V4-FLASH"],
)
def test_request_enforces_flash_only_model_without_echo(invalid: object) -> None:
    with pytest.raises(ValueError) as caught:
        _build_request(model=invalid)

    assert len(str(caught.value)) <= 80
    if isinstance(invalid, str) and invalid:
        assert invalid not in str(caught.value)


@pytest.mark.parametrize(
    "origin",
    [
        "https://api.deepseek.com",
        "https://api.deepseek.com/",
        "https://api.deepseek.com:443",
        "https://api.deepseek.com:443/",
        "HTTPS://API.DEEPSEEK.COM/",
    ],
)
def test_request_normalizes_official_origin_variants(origin: str) -> None:
    assert normalize_deepseek_responses_origin(origin) == (
        DEEPSEEK_RESPONSES_OFFICIAL_ORIGIN
    )
    assert _build_request(origin=origin).origin == DEEPSEEK_RESPONSES_OFFICIAL_ORIGIN


@pytest.mark.parametrize(
    "invalid",
    [
        None,
        True,
        "",
        " https://api.deepseek.com",
        "https://api.deepseek.com ",
        "https://api.deepseek.com/\n/",
        "http://api.deepseek.com",
        "https://deepseek.com",
        "https://api.deepseek.com.evil.example",
        "https://api.deepseek.com:",
        "https://api.deepseek.com:0443",
        "https://api.deepseek.com:8443",
        "https://user@api.deepseek.com",
        "https://api.deepseek.com/responses",
        "https://api.deepseek.com?mode=search",
        "https://api.deepseek.com#fragment",
        "https://api.deepseek.com?",
        "https://api.deepseek.com#",
        "https://api.deepseek.com/%2F",
        "https://[invalid",
    ],
)
def test_request_rejects_non_official_origin_without_echo(invalid: object) -> None:
    with pytest.raises(ValueError) as caught:
        _build_request(origin=invalid)

    assert len(str(caught.value)) <= 80
    if isinstance(invalid, str) and invalid:
        assert invalid not in str(caught.value)


@pytest.mark.parametrize(
    "forbidden",
    [
        "body",
        "domains",
        "settings",
        "principal_id",
        "window_id",
        "previous_response_id",
        "conversation",
        "metadata",
        "include",
        "store",
        "cache_key",
        "client",
        "transport",
    ],
)
def test_request_builder_rejects_caller_supplied_extra_fields(forbidden: str) -> None:
    with pytest.raises(TypeError):
        build_deepseek_responses_search_request(
            **_VALID_REQUEST, **{forbidden: "must not be accepted"}
        )


def test_adapter_module_has_no_unowned_runtime_dependency_or_parameter() -> None:
    module_path = Path(inspect.getfile(build_deepseek_responses_search_request))
    tree = ast.parse(module_path.read_text(encoding="utf-8"))
    imported = {
        alias.name
        for node in ast.walk(tree)
        if isinstance(node, ast.Import)
        for alias in node.names
    }
    imported.update(
        node.module or "" for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)
    )
    parameters = inspect.signature(build_deepseek_responses_search_request).parameters

    forbidden_imports = {
        "http.client",
        "httpx",
        "os",
        "pathlib",
        "socket",
        "urllib.request",
        "codex_rosetta.gateway.config",
        "codex_rosetta.gateway.providers",
        "codex_rosetta.gateway.config",
        "codex_rosetta.gateway.providers",
    }
    assert imported.isdisjoint(forbidden_imports)
    assert set(parameters) == {
        "query",
        "origin",
        "model",
        "max_output_tokens",
        "citation_limit",
        "timeout",
    }
    assert all(
        parameter.kind is inspect.Parameter.KEYWORD_ONLY
        for parameter in parameters.values()
    )


def _output_text(
    text: object = "Answer from the web.",
    annotations: object = None,
) -> dict[str, object]:
    return {
        "type": "output_text",
        "text": text,
        "annotations": [] if annotations is None else annotations,
    }


def _completed_response(
    *,
    content: object = None,
    usage: object = None,
) -> dict[str, object]:
    response: dict[str, object] = {
        "id": "opaque-response-id",
        "status": "completed",
        "output": [
            {"type": "reasoning", "id": "opaque-reasoning-id"},
            {
                "type": "web_search_call",
                "id": "opaque-search-call-id",
                "status": "completed",
            },
            {
                "type": "message",
                "content": [_output_text()] if content is None else content,
            },
        ],
    }
    if usage is not None:
        response["usage"] = usage
    return response


_DEFAULT_RESPONSE = object()


def _parse(
    response: object = _DEFAULT_RESPONSE, *, citation_limit: object = 5
) -> dict[str, object]:
    return parse_deepseek_responses_search_response(
        _completed_response() if response is _DEFAULT_RESPONSE else response,
        citation_limit=citation_limit,
    )


def _publish(
    response: object = _DEFAULT_RESPONSE,
    *,
    raw_response: object | None = None,
    citation_limit: object = 5,
    tokens: tuple[str, ...] = (),
) -> dict[str, object]:
    value = _completed_response() if response is _DEFAULT_RESPONSE else response
    if raw_response is None:
        raw_response = json.dumps(value, ensure_ascii=False).encode("utf-8")
    return publish_deepseek_responses_search_response(
        raw_response=raw_response,
        response=value,
        citation_limit=citation_limit,
        redactor=SecretRedactor(tokens),
    )


def _citation(url: object, **overrides: object) -> dict[str, object]:
    return {
        "type": "url_citation",
        "url": url,
        "title": "  Example title  ",
        "start_index": 0,
        "end_index": 6,
        **overrides,
    }


def test_parse_documented_shape_returns_only_provider_neutral_values() -> None:
    result = _parse(
        _completed_response(
            content=[
                _output_text(
                    "Source text",
                    [_citation("HTTPS://Example.COM:443/path?q=1#fragment")],
                )
            ],
            usage={
                "input_tokens": 12,
                "output_tokens": 7,
                "total_tokens": 19,
                "opaque_usage": "ignored",
            },
        )
    )

    assert result == {
        "output": "Source text",
        "results": [
            {
                "title": "Example title",
                "url": "https://example.com/path?q=1",
                "content": "Source",
            }
        ],
        "usage": {"input_tokens": 12, "output_tokens": 7, "total_tokens": 19},
    }
    rendered = repr(result)
    assert "opaque-response-id" not in rendered
    assert "opaque-search-call-id" not in rendered
    assert "opaque-reasoning-id" not in rendered


def test_parse_preserves_wire_order_across_messages_and_output_text_items() -> None:
    response = _completed_response()
    response["output"] = [
        {"type": "message", "content": [_output_text("  first ")]},
        {"type": "unknown", "payload": "ignored"},
        {"type": "web_search_call", "status": "completed"},
        {
            "type": "message",
            "content": [
                {"type": "unknown_content", "text": "ignored"},
                _output_text("second"),
                _output_text(" third  "),
            ],
        },
    ]

    assert _parse(response)["output"] == "first second third"


def test_completed_search_with_non_empty_text_and_zero_citations_is_valid() -> None:
    assert _parse() == {
        "output": "Answer from the web.",
        "results": [],
        "usage": {},
    }


@pytest.mark.parametrize(
    "response",
    [
        None,
        [],
        {"status": "completed", "output": []},
        {"status": "failed", "output": []},
        {"status": "completed", "output": "not-a-list"},
        _completed_response(content=[]),
        _completed_response(content=[_output_text("")]),
        _completed_response(content=[_output_text("   ")]),
        {
            "status": "completed",
            "output": [
                {"type": "web_search_call", "status": "in_progress"},
                {"type": "message", "content": [_output_text()]},
            ],
        },
    ],
)
def test_parse_fails_closed_without_completed_search_and_final_text(
    response: object,
) -> None:
    with pytest.raises(DeepSeekResponsesSearchParseError) as caught:
        _parse(response)

    assert str(caught.value) == "DeepSeek Responses search response is invalid"
    assert caught.value.__cause__ is None


def test_parse_ignores_unknown_item_content_and_annotation_types() -> None:
    response = _completed_response(
        content=[
            42,
            {"type": "unknown_content", "value": object()},
            _output_text(
                "answer",
                [
                    None,
                    {"type": "unknown_annotation", "value": object()},
                    _citation("https://example.com"),
                ],
            ),
        ]
    )
    output = cast(list[object], response["output"])
    output.insert(0, None)

    assert cast(list[dict[str, str]], _parse(response)["results"])[0]["url"] == (
        "https://example.com/"
    )


@pytest.mark.parametrize(
    "mutate",
    [
        lambda body: body.update(status=1),
        lambda body: body.update(output=()),
        lambda body: cast(
            dict[str, object], cast(list[object], body["output"])[1]
        ).update(status=1),
        lambda body: cast(
            dict[str, object], cast(list[object], body["output"])[2]
        ).update(content=()),
        lambda body: cast(
            dict[str, object],
            cast(
                list[object],
                cast(dict[str, object], cast(list[object], body["output"])[2])[
                    "content"
                ],
            )[0],
        ).update(text=1),
        lambda body: cast(
            dict[str, object],
            cast(
                list[object],
                cast(dict[str, object], cast(list[object], body["output"])[2])[
                    "content"
                ],
            )[0],
        ).update(annotations=()),
        lambda body: cast(
            list[object],
            cast(
                dict[str, object],
                cast(
                    list[object], cast(dict[str, object], body["output"][2])["content"]
                )[0],
            )["annotations"],
        ).append(_citation(1)),
    ],
)
def test_malformed_documented_containers_and_scalars_fail_closed(
    mutate: Callable[[dict[str, object]], object],
) -> None:
    response = _completed_response(
        content=[_output_text("answer", [_citation("https://example.com")])]
    )
    mutate(response)

    with pytest.raises(DeepSeekResponsesSearchParseError):
        _parse(response)


class _HostileKey:
    def __init__(self, target: str, hooks: list[str], *, spoof: bool) -> None:
        self.target = target
        self.hooks = hooks
        self.spoof = spoof

    def __hash__(self) -> int:
        self.hooks.append("hash")
        return hash(self.target)

    def __eq__(self, other: object) -> bool:
        self.hooks.append("eq")
        if not self.spoof:
            raise RuntimeError("caller-controlled-key")
        return other == self.target


def _replace_with_hostile_key(
    mapping: dict[object, object],
    key: str,
    hooks: list[str],
    *,
    spoof: bool,
) -> None:
    value = mapping.pop(key)
    mapping[_HostileKey(key, hooks, spoof=spoof)] = value
    hooks.clear()


@pytest.mark.parametrize(
    "location", ["root", "output", "content", "annotation", "usage"]
)
@pytest.mark.parametrize("spoof", [False, True], ids=["raises", "spoofs"])
def test_non_exact_dict_keys_fail_before_any_lookup_or_caller_hook(
    location: str, spoof: bool
) -> None:
    hooks: list[str] = []
    response = _completed_response(
        content=[_output_text("answer", [_citation("https://example.com")])],
        usage={"input_tokens": 1},
    )
    output = cast(list[dict[object, object]], response["output"])
    content = cast(list[dict[object, object]], output[2]["content"])
    annotation = cast(list[dict[object, object]], content[0]["annotations"])[0]
    usage = cast(dict[object, object], response["usage"])
    if location == "root":
        target = cast(dict[object, object], response)
        key = "status"
    elif location == "output":
        target = output[1]
        key = "type"
    elif location == "content":
        target = content[0]
        key = "type"
    elif location == "annotation":
        target = annotation
        key = "url"
    else:
        target = usage
        key = "input_tokens"
    _replace_with_hostile_key(target, key, hooks, spoof=spoof)

    with pytest.raises(DeepSeekResponsesSearchParseError) as caught:
        _parse(response)

    assert str(caught.value) == "DeepSeek Responses search response is invalid"
    assert caught.value.__cause__ is None
    assert hooks == []


@pytest.mark.parametrize(
    ("url", "expected"),
    [
        ("HTTP://Example.COM:80", "http://example.com/"),
        ("https://Example.COM:443/a?b=2#frag", "https://example.com/a?b=2"),
        ("https://Example.COM:8443", "https://example.com:8443/"),
        ("https://[2001:DB8::1]:443", "https://[2001:db8::1]/"),
    ],
)
def test_citation_url_canonicalization(url: str, expected: str) -> None:
    result = _parse(
        _completed_response(content=[_output_text("answer", [_citation(url)])])
    )

    assert cast(list[dict[str, str]], result["results"])[0]["url"] == expected


@pytest.mark.parametrize(
    "url",
    [
        "https://example.com/a b",
        "https://example.com/a\tb",
        "https://example.com/a\nb",
        "https://example.com/a\rb",
        "https://example.com/a\x00b",
        "https://example.com/a\x1fb",
        "https://example.com/a\x7fb",
        "https://example.com/?q=a\u00a0b",
    ],
)
def test_citation_url_rejects_whitespace_ascii_control_and_del_before_urlsplit(
    url: str,
) -> None:
    result = _parse(
        _completed_response(content=[_output_text("answer", [_citation(url)])])
    )

    assert result == {"output": "answer", "results": [], "usage": {}}


@pytest.mark.parametrize(
    "unicode_hostname",
    ["ｅxample.com", "éxample.com", "e\u0301xample.com", "例子.测试"],
)
def test_citation_url_rejects_unicode_hostname_and_cannot_duplicate_ascii_identity(
    unicode_hostname: str,
) -> None:
    annotations = [
        _citation("https://example.com", title="ascii"),
        _citation(f"https://{unicode_hostname}", title="unicode"),
    ]

    results = cast(
        list[dict[str, str]],
        _parse(_completed_response(content=[_output_text("answer", annotations)]))[
            "results"
        ],
    )

    assert [(item["title"], item["url"]) for item in results] == [
        ("ascii", "https://example.com/")
    ]


def test_kelvin_hostname_is_rejected_before_splitresult_lowercase() -> None:
    result = _parse(
        _completed_response(
            content=[
                _output_text(
                    "answer",
                    [_citation("https://K.com/", title="kelvin")],
                )
            ]
        )
    )

    assert result == {"output": "answer", "results": [], "usage": {}}


def test_kelvin_hostname_cannot_displace_ascii_canonical_citation() -> None:
    annotations = [
        _citation("https://K.com/", title="kelvin"),
        _citation("https://k.com/", title="ascii"),
    ]

    results = cast(
        list[dict[str, str]],
        _parse(_completed_response(content=[_output_text("answer", annotations)]))[
            "results"
        ],
    )

    assert [(item["title"], item["url"]) for item in results] == [
        ("ascii", "https://k.com/")
    ]


def test_canonical_citation_url_is_idempotent_and_reparseable() -> None:
    first = cast(
        list[dict[str, str]],
        _parse(
            _completed_response(
                content=[
                    _output_text(
                        "answer",
                        [_citation("HTTPS://Example.COM:443/path?q=1#fragment")],
                    )
                ]
            )
        )["results"],
    )[0]["url"]
    second = cast(
        list[dict[str, str]],
        _parse(
            _completed_response(content=[_output_text("answer", [_citation(first)])])
        )["results"],
    )[0]["url"]

    assert first == "https://example.com/path?q=1"
    assert second == first


@pytest.mark.parametrize(
    "url",
    [
        "ftp://example.com/file",
        "https://user@example.com/",
        "https://user:pass@example.com/",
        "https:///missing-host",
        "https://exa mple.com/",
        "https://./",
        "https://-bad.example/",
        "https://bad_host.example/",
        "https://example.com:invalid/",
        " https://example.com/",
    ],
)
def test_malformed_citation_url_is_skipped_without_losing_valid_answer(
    url: str,
) -> None:
    result = _parse(
        _completed_response(content=[_output_text("answer", [_citation(url)])])
    )

    assert result["output"] == "answer"
    assert result["results"] == []


def test_citations_dedupe_by_final_canonical_url_and_honor_limit() -> None:
    annotations = [
        _citation("HTTPS://EXAMPLE.COM:443#one", title="first"),
        _citation("https://example.com/#two", title="duplicate"),
        _citation("https://second.example", title="second"),
        _citation("https://third.example", title="third"),
    ]

    results = cast(
        list[dict[str, str]],
        _parse(
            _completed_response(content=[_output_text("answer", annotations)]),
            citation_limit=2,
        )["results"],
    )

    assert [(result["title"], result["url"]) for result in results] == [
        ("first", "https://example.com/"),
        ("second", "https://second.example/"),
    ]


def test_duplicate_citation_still_validates_documented_scalar_shape() -> None:
    annotations = [
        _citation("https://example.com", title="first"),
        _citation("HTTPS://EXAMPLE.COM:443#duplicate", title=object()),
    ]

    with pytest.raises(DeepSeekResponsesSearchParseError):
        _parse(_completed_response(content=[_output_text("answer", annotations)]))


@pytest.mark.parametrize("decision", ["invalid", "overlength", "duplicate", "limit"])
def test_malformed_title_fails_before_any_url_publication_decision(
    decision: str,
) -> None:
    first = _citation("https://example.com", title="first")
    if decision == "invalid":
        annotations = [_citation("ftp://example.com", title=object())]
        citation_limit = 5
    elif decision == "overlength":
        annotations = [_citation("https://example.com/" + ("x" * 8192), title=object())]
        citation_limit = 5
    elif decision == "duplicate":
        annotations = [
            first,
            _citation("HTTPS://EXAMPLE.COM:443#duplicate", title=object()),
        ]
        citation_limit = 5
    else:
        annotations = [
            first,
            _citation("https://second.example", title=object()),
        ]
        citation_limit = 1

    with pytest.raises(DeepSeekResponsesSearchParseError) as caught:
        _parse(
            _completed_response(content=[_output_text("answer", annotations)]),
            citation_limit=citation_limit,
        )

    assert str(caught.value) == "DeepSeek Responses search response is invalid"
    assert caught.value.__cause__ is None


def test_title_fallback_and_content_slice_use_only_final_bounded_values() -> None:
    hostname = f"{'a' * 600}.example"
    text = "x" * 1300
    result = _parse(
        _completed_response(
            content=[
                _output_text(
                    text,
                    [
                        _citation(
                            f"https://{hostname}",
                            title="  ",
                            start_index=0,
                            end_index=len(text),
                        )
                    ],
                )
            ]
        )
    )
    citation = cast(list[dict[str, str]], result["results"])[0]

    assert citation["title"] == hostname[:500]
    assert len(citation["title"]) == 500
    assert citation["content"] == text[:1200]
    assert len(citation["content"]) == 1200


@pytest.mark.parametrize(
    ("indexes", "expected"),
    [
        ({}, ""),
        ({"start_index": True, "end_index": 3}, ""),
        ({"start_index": -1, "end_index": 3}, ""),
        ({"start_index": 4, "end_index": 3}, ""),
        ({"start_index": 0, "end_index": 7}, ""),
        ({"start_index": 1, "end_index": 4}, "bcd"),
    ],
)
def test_citation_indexes_are_exact_bounded_and_local_to_same_text(
    indexes: dict[str, object], expected: str
) -> None:
    citation = _citation("https://example.com")
    citation.pop("start_index")
    citation.pop("end_index")
    citation.update(indexes)
    result = _parse(_completed_response(content=[_output_text("abcdef", [citation])]))

    assert cast(list[dict[str, str]], result["results"])[0]["content"] == expected


def test_pathless_url_at_raw_limit_is_checked_after_canonicalization() -> None:
    prefix = "https://example.com?"
    raw_at_limit = prefix + ("q" * (8192 - len(prefix)))
    raw_below_limit = prefix + ("q" * (8191 - len(prefix)))
    response = _completed_response(
        content=[
            _output_text(
                "answer",
                [_citation(raw_at_limit), _citation(raw_below_limit)],
            )
        ]
    )

    results = cast(list[dict[str, str]], _parse(response)["results"])

    assert len(raw_at_limit) == 8192
    assert len(results) == 1
    assert len(results[0]["url"]) == 8192
    assert results[0]["url"].startswith("https://example.com/?")


@pytest.mark.parametrize("length", [1, 64_000])
def test_final_output_accepts_exact_length_bounds(length: int) -> None:
    result = _parse(_completed_response(content=[_output_text("x" * length)]))

    assert len(cast(str, result["output"])) == length


def test_final_output_rejects_over_bound_after_ordered_join_and_trim() -> None:
    response = _completed_response(
        content=[_output_text(" " + ("x" * 32_001)), _output_text("x" * 32_000 + " ")]
    )

    with pytest.raises(DeepSeekResponsesSearchParseError):
        _parse(response)


def test_final_output_bounds_apply_after_large_edge_whitespace_is_trimmed() -> None:
    response = _completed_response(
        content=[
            _output_text((" " * 100_000) + "bounded"),
            _output_text(" value" + ("\n" * 100_000)),
        ]
    )

    assert _parse(response)["output"] == "bounded value"


@pytest.mark.parametrize("container", ["output", "content", "annotations", "usage"])
def test_recognized_containers_are_bounded_at_256_items(container: str) -> None:
    response = _completed_response()
    if container == "output":
        response["output"] = [None] * 257
    elif container == "content":
        cast(dict[str, object], cast(list[object], response["output"])[2])[
            "content"
        ] = [None] * 257
    elif container == "annotations":
        content = cast(
            list[dict[str, object]],
            cast(dict[str, object], cast(list[object], response["output"])[2])[
                "content"
            ],
        )
        content[0]["annotations"] = [None] * 257
    else:
        response["usage"] = {f"unknown-{index}": index for index in range(257)}

    with pytest.raises(DeepSeekResponsesSearchParseError):
        _parse(response)


def _response_with_aggregate_visits(annotation_count: int) -> dict[str, object]:
    shared_content = [_output_text("x")] * 255
    messages = [{"type": "message", "content": shared_content} for _ in range(15)]
    special_message = {
        "type": "message",
        "content": [_output_text("x", [{"type": "unknown"}] * annotation_count)],
    }
    return {
        "status": "completed",
        "output": [
            {"type": "web_search_call", "status": "completed"},
            *messages,
            special_message,
        ],
    }


def test_aggregate_visit_budget_accepts_4096_and_rejects_4097_atomically() -> None:
    accepted = _parse(_response_with_aggregate_visits(253))

    assert accepted["output"] == "x" * 3826
    assert accepted["results"] == []
    with pytest.raises(DeepSeekResponsesSearchParseError) as caught:
        _parse(_response_with_aggregate_visits(254))
    assert str(caught.value) == "DeepSeek Responses search response is invalid"
    assert caught.value.__cause__ is None


def test_shared_reference_dag_cannot_bypass_aggregate_visit_budget() -> None:
    shared_content = [_output_text("x")] * 256
    shared_message = {"type": "message", "content": shared_content}
    response = {
        "status": "completed",
        "output": [
            {"type": "web_search_call", "status": "completed"},
            *([shared_message] * 16),
        ],
    }

    with pytest.raises(DeepSeekResponsesSearchParseError):
        _parse(response)


def test_exact_string_and_key_budget_accepts_1m_chars_and_rejects_next_char() -> None:
    # The minimal valid shape below consumes 104 exact-string/key characters
    # besides the unknown root key itself.
    minimal = {
        "status": "completed",
        "output": [
            {"type": "web_search_call", "status": "completed"},
            {"type": "message", "content": [_output_text("x")]},
        ],
    }
    accepted = {**minimal}
    accepted["k" * (1_000_000 - 104)] = None
    rejected = {**minimal}
    rejected["k" * (1_000_001 - 104)] = None

    assert _parse(accepted)["output"] == "x"
    with pytest.raises(DeepSeekResponsesSearchParseError):
        _parse(rejected)


def test_string_budget_rejects_before_urlsplit_scans_over_limit_value(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = 0

    def unexpected_urlsplit(value: str):
        nonlocal calls
        del value
        calls += 1
        raise AssertionError("urlsplit must not run after the string budget is spent")

    monkeypatch.setattr(deepseek_search, "urlsplit", unexpected_urlsplit)
    response = _completed_response(
        content=[
            _output_text("x", [_citation("https://example.com/" + ("x" * 1_000_000))])
        ]
    )

    with pytest.raises(DeepSeekResponsesSearchParseError):
        _parse(response)

    assert calls == 0


@pytest.mark.parametrize(
    "usage",
    [
        [],
        {"input_tokens": True},
        {"output_tokens": -1},
        {"total_tokens": 1_000_000_001},
        {"input_tokens": 1.0},
    ],
)
def test_usage_rejects_malformed_recognized_values(usage: object) -> None:
    with pytest.raises(DeepSeekResponsesSearchParseError):
        _parse(_completed_response(usage=usage))


def test_usage_copies_only_exact_non_negative_bounded_integer_fields() -> None:
    usage = {
        "input_tokens": 0,
        "output_tokens": 1_000_000_000,
        "total_tokens": 100,
        "input_tokens_details": {"cached_tokens": 99},
    }

    assert _parse(_completed_response(usage=usage))["usage"] == {
        "input_tokens": 0,
        "output_tokens": 1_000_000_000,
        "total_tokens": 100,
    }


@pytest.mark.parametrize("citation_limit", [True, 0, 9, 5.0, "5"])
def test_parser_reuses_exact_s01_1_citation_limit_contract(
    citation_limit: object,
) -> None:
    with pytest.raises(DeepSeekResponsesSearchParseError):
        _parse(citation_limit=citation_limit)


class _HostileDict(dict[object, object]):
    def __init__(self, value: dict[object, object], hooks: list[str]) -> None:
        dict.__init__(self, value)
        self.hooks = hooks

    def _fail(self, hook: str) -> Never:
        self.hooks.append(hook)
        raise RuntimeError("caller-controlled-container")

    def __len__(self) -> int:
        self._fail("len")

    def __iter__(self):
        self._fail("iter")

    def __getitem__(self, key: object) -> object:
        del key
        self._fail("getitem")

    def get(self, key: object, default: object = None) -> object:
        del key, default
        self._fail("get")


class _HostileList(list[object]):
    def __init__(self, value: list[object], hooks: list[str]) -> None:
        list.__init__(self, value)
        self.hooks = hooks

    def _fail(self, hook: str) -> Never:
        self.hooks.append(hook)
        raise RuntimeError("caller-controlled-container")

    def __len__(self) -> int:
        self._fail("len")

    def __iter__(self):
        self._fail("iter")


class _HostileClassProperty:
    def __init__(self, hooks: list[str], behavior: str) -> None:
        self.hooks = hooks
        self.behavior = behavior

    @property
    def __class__(self) -> type:
        self.hooks.append("__class__")
        if self.behavior == "throw":
            raise RuntimeError("caller-controlled-class-body")
        return dict


def _type_with_hostile_metaclass(
    name: str,
    bases: tuple[type, ...],
    hooks: list[str],
) -> type:
    class _HostileMetaclass(type):
        @property
        def __mro__(self) -> Never:
            hooks.append("mro-property")
            raise RuntimeError("caller-controlled-metaclass-mro")

        def __getattribute__(self, attribute: str) -> Any:
            hooks.append(f"getattribute:{attribute}")
            raise RuntimeError("caller-controlled-metaclass-access")

        def __eq__(self, other: object) -> bool:
            del other
            hooks.append("eq")
            raise RuntimeError("caller-controlled-metaclass-comparison")

        __hash__ = type.__hash__

    return _HostileMetaclass(name, bases, {})


@pytest.mark.parametrize("location", ["output", "content", "annotation"])
@pytest.mark.parametrize("behavior", ["throw", "spoof"])
def test_arbitrary_item_class_property_is_never_executed_or_shape_relevant(
    location: str,
    behavior: str,
) -> None:
    hooks: list[str] = []
    hostile = _HostileClassProperty(hooks, behavior)
    response = _completed_response(content=[_output_text("answer")])
    output = cast(list[object], response["output"])
    message = cast(dict[str, object], output[2])
    content = cast(list[dict[str, object]], message["content"])
    if location == "output":
        output.insert(0, hostile)
    elif location == "content":
        cast(list[object], message["content"]).insert(0, hostile)
    else:
        content[0]["annotations"] = [hostile]

    assert _parse(response) == {
        "output": "answer",
        "results": [],
        "usage": {},
    }
    assert hooks == []


def test_unknown_item_ancestry_check_bypasses_custom_metaclass_hooks() -> None:
    hooks: list[str] = []
    hostile_type = _type_with_hostile_metaclass("UnknownItem", (object,), hooks)
    response = _completed_response(content=[hostile_type(), _output_text("answer")])

    assert _parse(response)["output"] == "answer"
    assert hooks == []


def test_dict_subclass_ancestry_check_bypasses_custom_metaclass_hooks() -> None:
    hooks: list[str] = []
    hostile_type = _type_with_hostile_metaclass("DictItem", (dict,), hooks)
    response = _completed_response()
    cast(list[object], response["output"]).insert(0, hostile_type())

    with pytest.raises(DeepSeekResponsesSearchParseError) as caught:
        _parse(response)

    assert str(caught.value) == "DeepSeek Responses search response is invalid"
    assert caught.value.__cause__ is None
    assert "caller-controlled" not in str(caught.value)
    assert hooks == []


@pytest.mark.parametrize(
    "location", ["root", "output", "item", "content", "annotations", "usage"]
)
def test_hostile_container_subclasses_fail_without_executing_hooks(
    location: str,
) -> None:
    hooks: list[str] = []
    response: object = _completed_response()
    body = response
    if location == "root":
        response = _HostileDict(cast(dict[object, object], body), hooks)
    elif location == "output":
        body["output"] = _HostileList(cast(list[object], body["output"]), hooks)
    elif location == "item":
        output = cast(list[object], body["output"])
        output[1] = _HostileDict(cast(dict[object, object], output[1]), hooks)
    elif location == "content":
        message = cast(dict[str, object], cast(list[object], body["output"])[2])
        message["content"] = _HostileList(cast(list[object], message["content"]), hooks)
    elif location == "annotations":
        content = cast(
            list[dict[str, object]],
            cast(dict[str, object], cast(list[object], body["output"])[2])["content"],
        )
        content[0]["annotations"] = _HostileList([], hooks)
    else:
        body["usage"] = _HostileDict({}, hooks)

    with pytest.raises(DeepSeekResponsesSearchParseError) as caught:
        _parse(response)

    assert hooks == []
    assert "caller-controlled-container" not in str(caught.value)


@pytest.mark.parametrize("location", ["status", "type", "text", "url", "title"])
def test_hostile_string_subclasses_fail_without_executing_hooks(location: str) -> None:
    hooks: list[str] = []
    response = _completed_response(
        content=[_output_text("answer", [_citation("https://example.com")])]
    )
    output = cast(list[dict[str, object]], response["output"])
    content = cast(list[dict[str, object]], output[2]["content"])
    annotation = cast(list[dict[str, object]], content[0]["annotations"])[0]
    if location == "status":
        response["status"] = _HookedStr("completed", hooks)
    elif location == "type":
        output[2]["type"] = _HookedStr("message", hooks)
    elif location == "text":
        content[0]["text"] = _HookedStr("answer", hooks)
    elif location == "url":
        annotation["url"] = _HookedStr("https://example.com", hooks)
    else:
        annotation["title"] = _HookedStr("title", hooks)

    with pytest.raises(DeepSeekResponsesSearchParseError):
        _parse(response)

    assert hooks == []


def test_hostile_integer_subclasses_never_execute_hooks() -> None:
    hooks: list[str] = []
    response = _completed_response(
        content=[
            _output_text(
                "answer",
                [
                    _citation(
                        "https://example.com",
                        start_index=_HookedInt(0, hooks),
                        end_index=_HookedInt(2, hooks),
                    )
                ],
            )
        ],
    )

    citation = cast(list[dict[str, str]], _parse(response)["results"])[0]
    assert citation["content"] == ""
    assert hooks == []


def test_hostile_usage_integer_subclass_fails_without_executing_hooks() -> None:
    hooks: list[str] = []

    with pytest.raises(DeepSeekResponsesSearchParseError):
        _parse(_completed_response(usage={"input_tokens": _HookedInt(1, hooks)}))

    assert hooks == []


def test_hostile_citation_limit_fails_with_static_parse_error_and_no_hooks() -> None:
    hooks: list[str] = []

    with pytest.raises(DeepSeekResponsesSearchParseError) as caught:
        _parse(citation_limit=_HookedInt(5, hooks))

    assert str(caught.value) == "DeepSeek Responses search response is invalid"
    assert hooks == []


def test_deterministic_response_micro_fuzz_reasserts_final_invariants() -> None:
    rng = random.Random(0x5012)
    for index in range(512):
        scheme = rng.choice(["http", "https", "HTTP", "HTTPS"])
        host = f"Sub{rng.randrange(10)}.Example.COM"
        default_port = ":80" if scheme.lower() == "http" else ":443"
        port = rng.choice(["", default_port, ":8443"])
        path = rng.choice(["", "/", f"/p/{index}"])
        fragment = f"#fragment-{rng.randrange(20)}"
        text = f"prefix-{index}-suffix"
        start = rng.randrange(len(text) + 1)
        end = rng.randrange(start, len(text) + 1)
        title = rng.choice(["", "  ", f" title {index} ", "t" * 700])
        annotation = _citation(
            f"{scheme}://{host}{port}{path}?n={index}{fragment}",
            title=title,
            start_index=start,
            end_index=end,
        )

        result = _parse(
            _completed_response(
                content=[_output_text(f" {text} ", [annotation])],
                usage={"input_tokens": index, "unknown": object()},
            ),
            citation_limit=8,
        )
        output = result["output"]
        results = cast(list[dict[str, str]], result["results"])
        usage = cast(dict[str, int], result["usage"])

        assert type(output) is str and 1 <= len(output) <= 64_000
        assert len(results) <= 8
        assert usage == {"input_tokens": index}
        assert all(set(item) == {"title", "url", "content"} for item in results)
        assert all(len(item["title"]) <= 500 for item in results)
        assert all(len(item["url"]) <= 8192 for item in results)
        assert all(len(item["content"]) <= 1200 for item in results)
        assert all(
            item["url"].split(":", 1)[0] in {"http", "https"} for item in results
        )
        assert all(
            "#" not in item["url"] and "@" not in item["url"] for item in results
        )


_COLLISION_MESSAGE = (
    "DeepSeek Responses search response contains a configured credential; "
    "response blocked"
)


def _assert_static_collision(caught: pytest.ExceptionInfo[ValueError]) -> None:
    assert type(caught.value) is DeepSeekResponsesSearchCredentialCollisionError
    assert caught.value.args == (_COLLISION_MESSAGE,)
    assert str(caught.value) == _COLLISION_MESSAGE
    assert caught.value.__cause__ is None
    assert caught.value.__context__ is None


@pytest.mark.parametrize("location", ["key", "value", "text"])
def test_publish_blocks_raw_exact_reflection_before_parser(
    location: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    token = "".join(("s01", "three", "-raw"))
    encoded = token.encode("utf-8")
    if location == "key":
        raw = b'{"' + encoded + b'":"safe"}'
    elif location == "value":
        raw = b'{"value":"' + encoded + b'"}'
    else:
        raw = b'{"text":"prefix-' + encoded + b'-suffix"}'
    parser_calls = 0

    def parser_must_not_run(*args: object, **kwargs: object) -> Never:
        del args, kwargs
        nonlocal parser_calls
        parser_calls += 1
        raise AssertionError("parser ran after a raw collision")

    monkeypatch.setattr(
        deepseek_search,
        "parse_deepseek_responses_search_response",
        parser_must_not_run,
    )

    with pytest.raises(DeepSeekResponsesSearchCredentialCollisionError) as caught:
        _publish(response=None, raw_response=raw, tokens=(token,))

    _assert_static_collision(caught)
    assert parser_calls == 0


@pytest.mark.parametrize(
    "raw_builder",
    [
        lambda: b'{"value":"s01\\u0074hree-semantic"}',
        lambda: b'{"value":"s01\\/three-semantic"}',
        lambda: b'{"value":"s01\\u0074hree-semantic","value":"safe"}',
        lambda: b'{"value":"s01-\\ud83d\\ude00-semantic"}',
    ],
    ids=["unicode-escape", "escaped-slash", "duplicate-member", "surrogate-pair"],
)
def test_publish_blocks_raw_json_semantic_reflection(
    raw_builder: Callable[[], bytes],
) -> None:
    raw = raw_builder()
    token = (
        "s01/three-semantic"
        if b"\\/" in raw
        else ("s01-\U0001f600-semantic" if b"ud83d" in raw else "s01three-semantic")
    )

    with pytest.raises(DeepSeekResponsesSearchCredentialCollisionError) as caught:
        _publish(response=None, raw_response=raw, tokens=(token,))

    _assert_static_collision(caught)


@pytest.mark.parametrize(
    "fragments",
    [
        ["s01", "three-", "joined"],
        ["  s01", "three-", "joined  "],
        ["ordinary s01", "three-", "joined suffix"],
    ],
    ids=["two-boundaries", "trimmed-edges", "ordinary-surrounding-text"],
)
def test_publish_blocks_token_reconstructed_by_ordered_output_join(
    fragments: list[str],
) -> None:
    token = "".join(("s01", "three-", "joined"))
    response = _completed_response(content=[_output_text(part) for part in fragments])

    with pytest.raises(DeepSeekResponsesSearchCredentialCollisionError) as caught:
        _publish(response, tokens=(token,))

    _assert_static_collision(caught)


def test_publish_blocks_hostname_lowercase_synthesis_in_final_exact_gate(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    token = "".join(("secret", ".example"))
    response = _completed_response(
        content=[
            _output_text(
                "answer",
                [_citation("HTTPS://SECRET.EXAMPLE:443#fragment", title="  ")],
            )
        ]
    )

    def detector_must_not_run(self: SecretRedactor) -> Never:
        del self
        raise AssertionError("literal detector ran after final exact collision")

    monkeypatch.setattr(
        SecretRedactor,
        "streaming_value_detector",
        detector_must_not_run,
    )

    with pytest.raises(DeepSeekResponsesSearchCredentialCollisionError) as caught:
        _publish(response, tokens=(token,))

    _assert_static_collision(caught)


def _cross_field_response(boundary: str) -> tuple[dict[str, object], str]:
    if boundary == "output-title":
        token = "".join(("answer", "Title"))
        return _completed_response(
            content=[
                _output_text(
                    "answer",
                    [_citation("https://example.com", title="Title", end_index=0)],
                )
            ]
        ), token
    if boundary == "title-url":
        token = "".join(("Title", "https://example.com/"))
        return _completed_response(
            content=[
                _output_text(
                    "answer",
                    [_citation("https://example.com", title="Title", end_index=0)],
                )
            ]
        ), token
    if boundary == "url-content":
        token = "".join(("https://example.com/", "answer"))
        return _completed_response(
            content=[
                _output_text(
                    "answer",
                    [_citation("https://example.com", title="Title", end_index=6)],
                )
            ]
        ), token
    if boundary == "adjacent-results":
        token = "".join(("piece", "Next"))
        return _completed_response(
            content=[
                _output_text(
                    "piece",
                    [
                        _citation(
                            "https://first.example",
                            title="First",
                            end_index=5,
                        ),
                        _citation(
                            "https://second.example",
                            title="Next",
                            end_index=0,
                        ),
                    ],
                )
            ]
        ), token
    token = "".join(('{"field":', "Title"))
    return _completed_response(
        content=[
            _output_text(
                '{"field":',
                [_citation("https://example.com", title="Title", end_index=0)],
            )
        ]
    ), token


@pytest.mark.parametrize(
    "boundary",
    [
        "output-title",
        "title-url",
        "url-content",
        "adjacent-results",
        "json-looking-output-title",
    ],
)
def test_publish_blocks_literal_cross_field_reconstruction(boundary: str) -> None:
    response, token = _cross_field_response(boundary)
    direct = _parse(response)

    assert not SecretRedactor((token,)).contains_exact(direct)
    with pytest.raises(DeepSeekResponsesSearchCredentialCollisionError) as caught:
        _publish(response, tokens=(token,))

    _assert_static_collision(caught)


@pytest.mark.parametrize(
    ("token", "output", "title"),
    [
        ("s01three-safe", "s01three-saf", "ordinary"),
        ("s01three-safe", "safe", "s01three-"),
        ("s01three-safe", "s01three-", "middle-safe"),
        ("CaseSensitive", "casesensitive", "ordinary"),
    ],
    ids=["similar-prefix", "reverse-order", "non-adjacent", "case-mismatch"],
)
def test_publish_safe_near_matches_do_not_false_positive(
    token: str, output: str, title: str
) -> None:
    response = _completed_response(
        content=[
            _output_text(
                output,
                [_citation("https://example.com", title=title, end_index=0)],
            )
        ]
    )

    assert _publish(response, tokens=(token,)) == _parse(response)


def test_publish_zero_token_redactor_is_exact_parser_equivalent() -> None:
    response = _completed_response(
        content=[
            _output_text(
                "answer",
                [_citation("https://example.com/path#fragment", title="Title")],
            )
        ],
        usage={"input_tokens": 11, "output_tokens": 7, "total_tokens": 18},
    )

    assert _publish(response) == _parse(response)


@pytest.mark.parametrize("field", ["output", "title", "content"])
def test_publish_zero_token_preserves_parser_values_with_lone_surrogates(
    field: str,
) -> None:
    surrogate = "\ud800"
    if field == "output":
        response = _completed_response(content=[_output_text(f"answer{surrogate}")])
    elif field == "title":
        response = _completed_response(
            content=[
                _output_text(
                    "answer",
                    [_citation("https://example.com", title=f"Title{surrogate}")],
                )
            ]
        )
    else:
        text = f"answer{surrogate}"
        response = _completed_response(
            content=[
                _output_text(
                    text,
                    [
                        _citation(
                            "https://example.com",
                            start_index=0,
                            end_index=len(text),
                        )
                    ],
                )
            ]
        )

    assert _publish(response, raw_response=b"not-json") == _parse(response)


@pytest.mark.parametrize(
    "output,title",
    [("\ud800s01", "three"), ("s01", "three\ud800")],
    ids=["surrogate-before-token", "token-before-surrogate"],
)
def test_publish_literal_detector_preserves_token_detection_around_surrogates(
    output: str, title: str
) -> None:
    token = "s01three"
    response = _completed_response(
        content=[
            _output_text(
                output,
                [_citation("https://example.com", title=title, end_index=0)],
            )
        ]
    )
    normalized = _parse(response)
    assert not SecretRedactor((token,)).contains_exact(normalized)

    with pytest.raises(DeepSeekResponsesSearchCredentialCollisionError) as caught:
        _publish(response, raw_response=b"not-json", tokens=(token,))

    _assert_static_collision(caught)


@pytest.mark.parametrize("token_index", [0, 1, 2])
def test_publish_multiple_tokens_are_order_and_duplicate_independent(
    token_index: int,
) -> None:
    tokens = (
        "".join(("raw", "-token")),
        "".join(("final", ".example")),
        "".join(("answer", "Title")),
    )
    if token_index == 0:
        response = _completed_response()
        raw = b'{"value":"raw-token"}'
    elif token_index == 1:
        response = _completed_response(
            content=[
                _output_text(
                    "answer",
                    [_citation("https://FINAL.EXAMPLE", title="  ")],
                )
            ]
        )
        raw = None
    else:
        response, _ = _cross_field_response("output-title")
        raw = None
    configured = (tokens[2], tokens[token_index], tokens[0], tokens[token_index])

    with pytest.raises(DeepSeekResponsesSearchCredentialCollisionError):
        _publish(response, raw_response=raw, tokens=configured)


class _HostileBytes(bytes):
    hooks: list[str]

    def __new__(cls, hooks: list[str]) -> _HostileBytes:
        instance = bytes.__new__(cls, b"{}")
        instance.hooks = hooks
        return instance

    def _fail(self, hook: str) -> Never:
        self.hooks.append(hook)
        raise RuntimeError("caller-controlled-bytes")

    def __len__(self) -> int:
        self._fail("len")

    def __iter__(self):
        self._fail("iter")

    def __bytes__(self) -> bytes:
        self._fail("bytes")

    def __str__(self) -> str:
        self._fail("str")

    def __repr__(self) -> str:
        self._fail("repr")


class _HostileRedactor(SecretRedactor):
    def __init__(self, hooks: list[str]) -> None:
        super().__init__(())
        self.hooks = hooks

    def contains_json_semantic(self, value: str | bytes) -> bool:
        del value
        self.hooks.append("contains_json_semantic")
        raise RuntimeError("caller-controlled-redactor")

    def contains_exact(self, value: Any) -> bool:
        del value
        self.hooks.append("contains_exact")
        raise RuntimeError("caller-controlled-redactor")

    def streaming_value_detector(self):
        self.hooks.append("streaming_value_detector")
        raise RuntimeError("caller-controlled-redactor")


class _FakeRedactor:
    def __init__(self, hooks: list[str]) -> None:
        self.hooks = hooks

    def contains_json_semantic(self, value: object) -> bool:
        del value
        self.hooks.append("contains_json_semantic")
        return False


@pytest.mark.parametrize("kind", ["bytes-subclass", "redactor-subclass", "fake"])
def test_publish_preflight_rejects_hostile_inputs_without_hooks(kind: str) -> None:
    hooks: list[str] = []
    raw: object = b"{}"
    redactor: object = SecretRedactor(())
    if kind == "bytes-subclass":
        raw = _HostileBytes(hooks)
    elif kind == "redactor-subclass":
        redactor = _HostileRedactor(hooks)
    else:
        redactor = _FakeRedactor(hooks)

    with pytest.raises(DeepSeekResponsesSearchParseError) as caught:
        publish_deepseek_responses_search_response(
            raw_response=raw,
            response=_completed_response(),
            citation_limit=5,
            redactor=redactor,
        )

    assert str(caught.value) == "DeepSeek Responses search response is invalid"
    assert caught.value.__cause__ is None
    assert caught.value.__context__ is None
    assert hooks == []


def test_publish_raw_size_bound_runs_before_redactor_or_parser(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[str] = []

    def raw_gate(self: SecretRedactor, value: str | bytes) -> bool:
        del self, value
        calls.append("redactor")
        return False

    def parser(*args: object, **kwargs: object) -> dict[str, object]:
        del args, kwargs
        calls.append("parser")
        return {}

    monkeypatch.setattr(SecretRedactor, "contains_json_semantic", raw_gate)
    monkeypatch.setattr(
        deepseek_search, "parse_deepseek_responses_search_response", parser
    )

    with pytest.raises(DeepSeekResponsesSearchParseError):
        _publish(
            raw_response=b"x" * (DEEPSEEK_RESPONSES_SEARCH_RESPONSE_MAX_BYTES + 1),
        )

    assert calls == []


def test_publish_accepts_exact_raw_size_ceiling() -> None:
    assert (
        _publish(
            raw_response=b"x" * DEEPSEEK_RESPONSES_SEARCH_RESPONSE_MAX_BYTES,
        )
        == _parse()
    )


def test_publish_preserves_hostile_response_parser_contract_without_hooks() -> None:
    hooks: list[str] = []
    response = _HostileDict(cast(dict[object, object], _completed_response()), hooks)

    with pytest.raises(DeepSeekResponsesSearchParseError) as caught:
        _publish(response, raw_response=b"not-json")

    assert str(caught.value) == "DeepSeek Responses search response is invalid"
    assert caught.value.__cause__ is None
    assert hooks == []


def test_publish_calls_two_gates_around_parser_in_exact_order(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[str] = []
    exact_depth = 0
    raw_gate = SecretRedactor.contains_json_semantic
    exact_gate = SecretRedactor.contains_exact
    detector_gate = SecretRedactor.streaming_value_detector
    parser = deepseek_search.parse_deepseek_responses_search_response

    def wrapped_raw(self: SecretRedactor, value: str | bytes) -> bool:
        calls.append("raw")
        return raw_gate(self, value)

    def wrapped_parser(
        response: object, *, citation_limit: object
    ) -> dict[str, object]:
        calls.append("parser")
        return parser(response, citation_limit=citation_limit)

    def wrapped_exact(self: SecretRedactor, value: Any) -> bool:
        nonlocal exact_depth
        if exact_depth == 0:
            calls.append("exact")
        exact_depth += 1
        try:
            return exact_gate(self, value)
        finally:
            exact_depth -= 1

    def wrapped_detector(self: SecretRedactor):
        calls.append("literal")
        return detector_gate(self)

    monkeypatch.setattr(SecretRedactor, "contains_json_semantic", wrapped_raw)
    monkeypatch.setattr(
        deepseek_search, "parse_deepseek_responses_search_response", wrapped_parser
    )
    monkeypatch.setattr(SecretRedactor, "contains_exact", wrapped_exact)
    monkeypatch.setattr(SecretRedactor, "streaming_value_detector", wrapped_detector)

    assert _publish() == _parse()
    assert calls == ["raw", "exact", "parser", "exact", "literal"]


@pytest.mark.parametrize("operation", ["raw", "exact", "detector", "feed", "finish"])
def test_publish_redactor_internal_failures_are_static_parse_errors(
    operation: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    finish_calls = 0

    class FailingDetector:
        def feed(self, value: bytes) -> bool:
            del value
            if operation == "feed":
                raise RuntimeError("sensitive-internal-detail")
            return False

        def finish(self) -> None:
            nonlocal finish_calls
            finish_calls += 1
            if operation == "finish":
                raise RuntimeError("sensitive-internal-detail")

    if operation == "raw":
        monkeypatch.setattr(
            SecretRedactor,
            "contains_json_semantic",
            lambda self, value: (_ for _ in ()).throw(
                RuntimeError("sensitive-internal-detail")
            ),
        )
        raw = b"not-json"
    elif operation == "exact":
        monkeypatch.setattr(
            SecretRedactor,
            "contains_exact",
            lambda self, value: (_ for _ in ()).throw(
                RuntimeError("sensitive-internal-detail")
            ),
        )
        raw = b"not-json"
    else:
        if operation == "detector":
            monkeypatch.setattr(
                SecretRedactor,
                "streaming_value_detector",
                lambda self: (_ for _ in ()).throw(
                    RuntimeError("sensitive-internal-detail")
                ),
            )
        else:
            monkeypatch.setattr(
                SecretRedactor,
                "streaming_value_detector",
                lambda self: FailingDetector(),
            )
        raw = b"not-json"

    with pytest.raises(DeepSeekResponsesSearchParseError) as caught:
        _publish(raw_response=raw)

    assert str(caught.value) == "DeepSeek Responses search response is invalid"
    assert "sensitive-internal-detail" not in str(caught.value)
    assert caught.value.__cause__ is None
    assert caught.value.__context__ is None
    if operation in {"feed", "finish"}:
        assert finish_calls == 1


@pytest.mark.parametrize("operation", ["raw", "exact", "detector"])
def test_publish_redactor_memory_errors_propagate(
    operation: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    if operation == "raw":
        monkeypatch.setattr(
            SecretRedactor,
            "contains_json_semantic",
            lambda self, value: (_ for _ in ()).throw(MemoryError()),
        )
        raw = b"not-json"
    elif operation == "exact":
        monkeypatch.setattr(
            SecretRedactor,
            "contains_exact",
            lambda self, value: (_ for _ in ()).throw(MemoryError()),
        )
        raw = b"not-json"
    else:
        monkeypatch.setattr(
            SecretRedactor,
            "streaming_value_detector",
            lambda self: (_ for _ in ()).throw(MemoryError()),
        )
        raw = b"not-json"

    with pytest.raises(MemoryError):
        _publish(raw_response=raw)


def test_publish_public_contract_is_keyword_only_and_bounded() -> None:
    parameters = inspect.signature(
        publish_deepseek_responses_search_response
    ).parameters

    assert list(parameters) == [
        "raw_response",
        "response",
        "citation_limit",
        "redactor",
    ]
    assert all(
        parameter.kind is inspect.Parameter.KEYWORD_ONLY
        for parameter in parameters.values()
    )
    assert DEEPSEEK_RESPONSES_SEARCH_RESPONSE_MAX_BYTES == 4_194_304


def test_parser_module_has_no_unowned_runtime_importer() -> None:
    module_path = Path(inspect.getfile(parse_deepseek_responses_search_response))
    tree = ast.parse(module_path.read_text(encoding="utf-8"))
    imported = {
        alias.name
        for node in ast.walk(tree)
        if isinstance(node, ast.Import)
        for alias in node.names
    }
    imported.update(
        node.module or "" for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)
    )
    assert imported.isdisjoint(
        {
            "http.client",
            "httpx",
            "os",
            "pathlib",
            "socket",
            "urllib.request",
            "codex_rosetta.gateway.config",
            "codex_rosetta.gateway.providers",
            "codex_rosetta.gateway.config",
            "codex_rosetta.gateway.providers",
        }
    )
    assert "codex_rosetta.observability.redaction" in imported

    repository_root = module_path.parents[3]
    import_text = "codex_rosetta.gateway.deepseek_responses_search"
    production_importers = []
    for source in (repository_root / "src").rglob("*.py"):
        if source == module_path:
            continue
        if import_text in source.read_text(encoding="utf-8"):
            production_importers.append(source)
    assert production_importers == []


class _FakeResponsesClient:
    instances: list[_FakeResponsesClient] = []

    def __init__(self, *args: object, **kwargs: object) -> None:
        self.args = args
        self.kwargs = kwargs
        self.closed = False
        self.__class__.instances.append(self)

    async def __aenter__(self) -> _FakeResponsesClient:
        return self

    async def __aexit__(self, *args: object) -> None:
        del args
        self.closed = True


def _response_bytes(response: object | None = None) -> bytes:
    value = _completed_response() if response is None else response
    return json.dumps(value, ensure_ascii=False).encode("utf-8")


@pytest.mark.asyncio
async def test_client_composes_one_official_bounded_request(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _FakeResponsesClient.instances = []
    calls: list[dict[str, object]] = []

    async def bounded(
        client: object, method: str, url: str, **kwargs: object
    ) -> BoundedHttpResponse:
        calls.append({"client": client, "method": method, "url": url, **kwargs})
        return BoundedHttpResponse(200, {}, _response_bytes())

    monkeypatch.setattr(deepseek_search, "AsyncClient", _FakeResponsesClient)
    monkeypatch.setattr(deepseek_search, "request_bounded_response", bounded)

    result = await deepseek_search.DeepSeekResponsesSearchClient("test-secret").search(
        " current release notes "
    )

    assert result["output"] == "Answer from the web."
    assert len(calls) == 1
    call = calls[0]
    assert call["method"] == "POST"
    assert call["url"] == "https://api.deepseek.com/responses"
    assert call["headers"] == {
        "Authorization": "Bearer test-secret",
        "Content-Type": "application/json",
    }
    assert call["json"] == {
        "model": "deepseek-v4-flash",
        "input": _EXPECTED_PROMPT,
        "tools": [{"type": "web_search"}],
        "tool_choice": {"type": "web_search"},
        "max_output_tokens": 1024,
    }
    assert call["max_success_bytes"] == DEEPSEEK_RESPONSES_SEARCH_RESPONSE_MAX_BYTES
    assert call["max_error_bytes"] == DEEPSEEK_RESPONSES_SEARCH_RESPONSE_MAX_BYTES
    assert call["allow_redirects"] is False
    assert _FakeResponsesClient.instances[0].kwargs == {
        "timeout": 120.0,
        "max_redirects": 0,
    }


@pytest.mark.asyncio
async def test_client_uses_one_response_for_raw_decode_and_publication_in_order(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    raw = _response_bytes()
    calls: list[dict[str, object]] = []
    decoded_inputs: list[object] = []
    original_decode = deepseek_search._decode_deepseek_response
    original_raw_gate = deepseek_search._redactor_contains_json_semantic
    original_parser = deepseek_search.parse_deepseek_responses_search_response
    original_exact_gate = deepseek_search._redactor_contains_exact
    original_literal_gate = (
        deepseek_search._literal_publication_sequence_contains_credential
    )
    original_publish = deepseek_search._publish_after_raw_gate
    publish_calls = 0

    async def bounded(
        client: object, method: str, url: str, **kwargs: object
    ) -> BoundedHttpResponse:
        calls.append({"client": client, "method": method, "url": url, **kwargs})
        return BoundedHttpResponse(200, {}, raw)

    def decode(value: bytes) -> object:
        decoded_inputs.append(value)
        return original_decode(value)

    def raw_gate(redactor: SecretRedactor, value: bytes) -> bool:
        calls.append({"event": "raw_gate", "value": value})
        return original_raw_gate(redactor, value)

    def parser(value: object, *, citation_limit: object) -> dict[str, object]:
        calls.append({"event": "parser"})
        return original_parser(value, citation_limit=citation_limit)

    def exact_gate(redactor: SecretRedactor, value: dict[str, object]) -> bool:
        calls.append({"event": "final_exact_gate"})
        return original_exact_gate(redactor, value)

    def literal_gate(redactor: SecretRedactor, value: dict[str, object]) -> bool:
        calls.append({"event": "final_literal_gate"})
        return original_literal_gate(redactor, value)

    def publish(
        *, response: object, citation_limit: object, redactor: SecretRedactor
    ) -> dict[str, object]:
        nonlocal publish_calls
        publish_calls += 1
        return original_publish(
            response=response, citation_limit=citation_limit, redactor=redactor
        )

    monkeypatch.setattr(deepseek_search, "AsyncClient", _FakeResponsesClient)
    monkeypatch.setattr(deepseek_search, "request_bounded_response", bounded)
    monkeypatch.setattr(deepseek_search, "_decode_deepseek_response", decode)
    monkeypatch.setattr(deepseek_search, "_redactor_contains_json_semantic", raw_gate)
    monkeypatch.setattr(
        deepseek_search, "parse_deepseek_responses_search_response", parser
    )
    monkeypatch.setattr(deepseek_search, "_redactor_contains_exact", exact_gate)
    monkeypatch.setattr(
        deepseek_search,
        "_literal_publication_sequence_contains_credential",
        literal_gate,
    )
    monkeypatch.setattr(deepseek_search, "_publish_after_raw_gate", publish)

    result = await deepseek_search.DeepSeekResponsesSearchClient("test-secret").search(
        "current release notes"
    )

    assert result["output"] == "Answer from the web."
    assert len(calls) == 5
    assert len(decoded_inputs) == 1
    assert decoded_inputs[0] is raw
    assert publish_calls == 1
    assert [entry["event"] for entry in calls[1:]] == [
        "raw_gate",
        "parser",
        "final_exact_gate",
        "final_literal_gate",
    ]


@pytest.mark.asyncio
async def test_client_raw_collision_short_circuits_decode_and_publication(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    credential = "test-secret"
    raw = b'{"value":"test-secret"}'
    transport_calls = 0
    decode_calls = 0
    publication_calls = 0

    async def bounded(*args: object, **kwargs: object) -> BoundedHttpResponse:
        nonlocal transport_calls
        del args, kwargs
        transport_calls += 1
        return BoundedHttpResponse(200, {}, raw)

    def decode_must_not_run(value: bytes) -> Never:
        nonlocal decode_calls
        del value
        decode_calls += 1
        raise AssertionError("decode ran after a raw credential collision")

    def publication_must_not_run(**kwargs: object) -> Never:
        nonlocal publication_calls
        del kwargs
        publication_calls += 1
        raise AssertionError("publication ran after a raw credential collision")

    monkeypatch.setattr(deepseek_search, "AsyncClient", _FakeResponsesClient)
    monkeypatch.setattr(deepseek_search, "request_bounded_response", bounded)
    monkeypatch.setattr(
        deepseek_search, "_decode_deepseek_response", decode_must_not_run
    )
    monkeypatch.setattr(
        deepseek_search, "_publish_after_raw_gate", publication_must_not_run
    )

    with pytest.raises(DeepSeekResponsesSearchCredentialCollisionError) as caught:
        await deepseek_search.DeepSeekResponsesSearchClient(credential).execute("q")

    _assert_static_collision(caught)
    assert transport_calls == 1
    assert decode_calls == 0
    assert publication_calls == 0
    module_path = Path(inspect.getfile(deepseek_search))
    frame = caught.value.__traceback__
    while frame is not None:
        if frame.tb_frame.f_code.co_filename == str(module_path):
            values = tuple(frame.tb_frame.f_locals.values())
            assert credential not in values
            assert raw not in values
        frame = frame.tb_next


@pytest.mark.asyncio
async def test_client_final_collision_is_static_and_has_no_result(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    credential = "secret.example"
    response = _completed_response(
        content=[
            _output_text(
                "answer",
                [_citation("HTTPS://SECRET.EXAMPLE:443#fragment", title="  ")],
            )
        ]
    )
    raw = _response_bytes(response)
    assert credential.encode() not in raw
    events: list[str] = []
    transport_calls = 0
    original_raw_gate = deepseek_search._redactor_contains_json_semantic
    original_parser = deepseek_search.parse_deepseek_responses_search_response
    original_exact_gate = deepseek_search._redactor_contains_exact

    async def bounded(*args: object, **kwargs: object) -> BoundedHttpResponse:
        nonlocal transport_calls
        del args, kwargs
        transport_calls += 1
        return BoundedHttpResponse(200, {}, raw)

    def raw_gate(redactor: SecretRedactor, value: bytes) -> bool:
        events.append("raw_gate")
        return original_raw_gate(redactor, value)

    def parser(value: object, *, citation_limit: object) -> dict[str, object]:
        events.append("parser")
        return original_parser(value, citation_limit=citation_limit)

    def exact_gate(redactor: SecretRedactor, value: dict[str, object]) -> bool:
        events.append("final_exact_gate")
        return original_exact_gate(redactor, value)

    monkeypatch.setattr(deepseek_search, "AsyncClient", _FakeResponsesClient)
    monkeypatch.setattr(deepseek_search, "request_bounded_response", bounded)
    monkeypatch.setattr(deepseek_search, "_redactor_contains_json_semantic", raw_gate)
    monkeypatch.setattr(
        deepseek_search, "parse_deepseek_responses_search_response", parser
    )
    monkeypatch.setattr(deepseek_search, "_redactor_contains_exact", exact_gate)

    with pytest.raises(DeepSeekResponsesSearchCredentialCollisionError) as caught:
        await deepseek_search.DeepSeekResponsesSearchClient(credential).execute("q")

    _assert_static_collision(caught)
    assert transport_calls == 1
    assert events == ["raw_gate", "parser", "final_exact_gate"]
    module_path = Path(inspect.getfile(deepseek_search))
    frame = caught.value.__traceback__
    while frame is not None:
        if frame.tb_frame.f_code.co_filename == str(module_path):
            values = tuple(frame.tb_frame.f_locals.values())
            assert credential not in values
            assert raw not in values
        frame = frame.tb_next


class _NonBoundedResponsesEnvelope:
    """A lookalike response that must not cross the bounded transport seam."""

    status_code = 200
    content = b"{}"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("case", "expected_category", "expected_status"),
    [
        (
            "connection",
            deepseek_search.DeepSeekSearchErrorCategory.TRANSPORT_ERROR,
            None,
        ),
        ("timeout", deepseek_search.DeepSeekSearchErrorCategory.TIMEOUT, None),
        (
            "wrapped_timeout",
            deepseek_search.DeepSeekSearchErrorCategory.TIMEOUT,
            None,
        ),
        ("body_limit", deepseek_search.DeepSeekSearchErrorCategory.BODY_LIMIT, None),
        (
            "oversized_content",
            deepseek_search.DeepSeekSearchErrorCategory.BODY_LIMIT,
            None,
        ),
        (
            "malformed_json",
            deepseek_search.DeepSeekSearchErrorCategory.INVALID_JSON,
            None,
        ),
        (
            "invalid_shape",
            deepseek_search.DeepSeekSearchErrorCategory.INVALID_SHAPE,
            None,
        ),
        (
            "non_bounded",
            deepseek_search.DeepSeekSearchErrorCategory.INVALID_SHAPE,
            None,
        ),
        ("http", deepseek_search.DeepSeekSearchErrorCategory.HTTP_ERROR, 503),
    ],
)
async def test_client_fake_transport_failure_matrix_is_bounded_and_single_attempt(
    monkeypatch: pytest.MonkeyPatch,
    case: str,
    expected_category: deepseek_search.DeepSeekSearchErrorCategory,
    expected_status: int | None,
) -> None:
    credential = "test-secret"
    raw = b"malformed-json"
    calls = 0

    async def bounded(*args: object, **kwargs: object) -> object:
        nonlocal calls
        del args, kwargs
        calls += 1
        if case == "connection":
            raise deepseek_search.UpstreamConnectionError("upstream test-secret")
        if case == "timeout":
            raise TimeoutError("timed out test-secret")
        if case == "wrapped_timeout":
            timeout = HttpTimeoutError(
                "timed out test-secret",
                url="https://api.deepseek.com/responses",
                timeout=120.0,
            )
            raise deepseek_search.UpstreamConnectionError(
                "wrapped timeout test-secret"
            ) from timeout
        if case == "body_limit":
            raise deepseek_search.UpstreamResponseTooLargeError("test-secret too large")
        if case == "oversized_content":
            return BoundedHttpResponse(
                200,
                {},
                b"x" * (DEEPSEEK_RESPONSES_SEARCH_RESPONSE_MAX_BYTES + 1),
            )
        if case == "malformed_json":
            return BoundedHttpResponse(200, {}, raw)
        if case == "invalid_shape":
            return BoundedHttpResponse(200, {}, b'{"status":"completed","output":[]}')
        if case == "non_bounded":
            return _NonBoundedResponsesEnvelope()
        return BoundedHttpResponse(503, {}, b'{"upstream":"private test text"}')

    monkeypatch.setattr(deepseek_search, "AsyncClient", _FakeResponsesClient)
    monkeypatch.setattr(deepseek_search, "request_bounded_response", bounded)
    with pytest.raises(deepseek_search.DeepSeekSearchError) as caught:
        await deepseek_search.DeepSeekResponsesSearchClient(credential).search("q")

    error = caught.value
    assert calls == 1
    assert error.category is expected_category
    assert error.status_code == expected_status
    assert error.args == (expected_category.value,)
    assert error.__cause__ is None
    assert error.__context__ is None
    assert credential not in str(error)
    assert credential not in repr(error)
    assert "private test text" not in str(error)
    assert "private test text" not in repr(error)
    module_path = Path(inspect.getfile(deepseek_search))
    frame = error.__traceback__
    while frame is not None:
        if frame.tb_frame.f_code.co_filename == str(module_path):
            values = tuple(frame.tb_frame.f_locals.values())
            assert credential not in values
            assert raw not in values
            assert all(value is not raw for value in values)
        frame = frame.tb_next


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [400, 401, 402, 403, 422, 429, 500, 503])
async def test_client_maps_status_to_bounded_static_error(
    monkeypatch: pytest.MonkeyPatch, status: int
) -> None:
    _FakeResponsesClient.instances = []

    async def bounded(*args: object, **kwargs: object) -> BoundedHttpResponse:
        del args, kwargs
        return BoundedHttpResponse(status, {}, b'{"upstream":"private"}')

    monkeypatch.setattr(deepseek_search, "AsyncClient", _FakeResponsesClient)
    monkeypatch.setattr(deepseek_search, "request_bounded_response", bounded)
    with pytest.raises(deepseek_search.DeepSeekSearchError) as caught:
        await deepseek_search.DeepSeekResponsesSearchClient("test-secret").search("q")
    assert (
        caught.value.category is deepseek_search.DeepSeekSearchErrorCategory.HTTP_ERROR
    )
    assert caught.value.status_code == status
    assert caught.value.args == ("http_error",)
    assert caught.value.__cause__ is None
    assert caught.value.__context__ is None
    assert "private" not in str(caught.value)
    assert "test-secret" not in str(caught.value)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "kwargs",
    [
        {"model": "deepseek-v4-pro"},
        {"max_output_tokens": 1024.0},
        {"citation_limit": 0},
        {"citation_limit": 9},
    ],
)
async def test_client_rejects_invalid_controls_before_client_or_transport(
    monkeypatch: pytest.MonkeyPatch, kwargs: dict[str, object]
) -> None:
    _FakeResponsesClient.instances = []
    calls: list[object] = []

    async def bounded(*args: object, **kwargs: object) -> BoundedHttpResponse:
        calls.append((args, kwargs))
        return BoundedHttpResponse(200, {}, _response_bytes())

    monkeypatch.setattr(deepseek_search, "AsyncClient", _FakeResponsesClient)
    monkeypatch.setattr(deepseek_search, "request_bounded_response", bounded)
    with pytest.raises(ValueError):
        await deepseek_search.DeepSeekResponsesSearchClient("test-secret").search(
            "q", **kwargs
        )
    assert _FakeResponsesClient.instances == []
    assert calls == []


@pytest.mark.asyncio
async def test_client_preserves_cancelled_error_and_memory_error_identity(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(deepseek_search, "AsyncClient", _FakeResponsesClient)

    async def cancelled(*args: object, **kwargs: object) -> BoundedHttpResponse:
        del args, kwargs
        raise asyncio.CancelledError

    monkeypatch.setattr(deepseek_search, "request_bounded_response", cancelled)
    with pytest.raises(asyncio.CancelledError) as cancelled_error:
        await deepseek_search.DeepSeekResponsesSearchClient("test-secret").search("q")
    assert cancelled_error.value.__class__ is asyncio.CancelledError

    memory_error = MemoryError("allocation")

    async def exhausted(*args: object, **kwargs: object) -> BoundedHttpResponse:
        del args, kwargs
        raise memory_error

    monkeypatch.setattr(deepseek_search, "request_bounded_response", exhausted)
    with pytest.raises(MemoryError) as caught:
        await deepseek_search.DeepSeekResponsesSearchClient("test-secret").search("q")
    assert caught.value is memory_error


@pytest.mark.asyncio
async def test_client_error_traceback_does_not_retain_raw_or_decoded_values(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    raw = _response_bytes()

    async def bounded(*args: object, **kwargs: object) -> BoundedHttpResponse:
        del args, kwargs
        return BoundedHttpResponse(500, {}, raw)

    monkeypatch.setattr(deepseek_search, "AsyncClient", _FakeResponsesClient)
    monkeypatch.setattr(deepseek_search, "request_bounded_response", bounded)
    with pytest.raises(deepseek_search.DeepSeekSearchError) as caught:
        await deepseek_search.DeepSeekResponsesSearchClient("test-secret").search("q")

    frame = caught.value.__traceback__
    while frame is not None:
        if frame.tb_frame.f_code.co_filename != str(
            Path(inspect.getfile(deepseek_search))
        ):
            frame = frame.tb_next
            continue
        locals_ = frame.tb_frame.f_locals
        assert raw not in locals_.values()
        assert "test-secret" not in locals_.values()
        assert all(value is not raw for value in locals_.values())
        frame = frame.tb_next


@pytest.mark.parametrize(
    ("origin", "accepted"),
    [
        ("https://api.deepseek.com", True),
        ("https://api.deepseek.com/", True),
        ("https://api.deepseek.com:443", True),
        ("https://api.deepseek.com:443/", True),
        ("HTTPS://API.DEEPSEEK.COM:443/", True),
        (None, False),
        (True, False),
        ("", False),
        (" https://api.deepseek.com", False),
        ("https://api.deepseek.com ", False),
        ("https://api.deepseek.com\n/", False),
        ("http://api.deepseek.com", False),
        ("https://deepseek.com", False),
        ("https://api.deepseek.com.evil.example", False),
        ("https://api.deepseek.com:444", False),
        ("https://api.deepseek.com:0443", False),
        ("https://user@api.deepseek.com", False),
        ("https://api.deepseek.com/responses", False),
        ("https://api.deepseek.com?mode=search", False),
        ("https://api.deepseek.com#fragment", False),
        ("https://api.deepseek.com?", False),
        ("https://api.deepseek.com#", False),
        ("https://api.deepseek.com/%2F", False),
        ("https://[invalid", False),
    ],
)
def test_pure_origin_validator_matches_s01_4_semantics(
    origin: object, accepted: bool
) -> None:
    pure_origin = _load_pure_origin_module()
    if accepted:
        expected = DEEPSEEK_RESPONSES_OFFICIAL_ORIGIN
        assert pure_origin.normalize_deepseek_origin(origin) == expected
        assert pure_origin.normalize_deepseek_responses_origin(origin) == expected
        assert pure_origin.normalize_deepseek_search_origin(origin) == expected
        assert deepseek_search.normalize_deepseek_responses_origin(origin) == expected
        return

    with pytest.raises(ValueError) as pure_error:
        pure_origin.normalize_deepseek_origin(origin)
    with pytest.raises(ValueError) as adapter_error:
        deepseek_search.normalize_deepseek_responses_origin(origin)
    assert str(pure_error.value) == "DeepSeek origin must be the official HTTPS root"
    assert pure_error.value.__cause__ is None
    assert pure_error.value.__context__ is None
    assert len(str(pure_error.value)) <= 80
    if isinstance(origin, str) and origin:
        assert origin not in str(pure_error.value)
    frame = pure_error.value.__traceback__
    while frame is not None:
        if frame.tb_frame.f_code.co_filename == str(_PURE_ORIGIN_PATH):
            assert all(value != origin for value in frame.tb_frame.f_locals.values())
        frame = frame.tb_next
    assert str(adapter_error.value) == (
        "DeepSeek Responses origin must be the official HTTPS root"
    )


def test_pure_origin_module_has_only_stdlib_imports() -> None:
    tree = ast.parse(_PURE_ORIGIN_PATH.read_text(encoding="utf-8"))
    imported = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(alias.name.split(".", 1)[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module.split(".", 1)[0])
    assert imported == {"urllib"}
    forbidden = {
        "codex_rosetta",
        "deepseek_web_search_smoke",
        "httpx",
        "requests",
        "socket",
        "pathlib",
    }
    assert imported.isdisjoint(forbidden)


def test_pure_origin_import_isolated_from_runtime_modules() -> None:
    probe = "\n".join(
        [
            "import importlib.util",
            "import sys",
            f"path = {str(_PURE_ORIGIN_PATH)!r}",
            "spec = importlib.util.spec_from_file_location('isolated_origin', path)",
            "assert spec is not None and spec.loader is not None",
            "module = importlib.util.module_from_spec(spec)",
            "spec.loader.exec_module(module)",
            "assert module.normalize_deepseek_origin('HTTPS://API.DEEPSEEK.COM:443/') == 'https://api.deepseek.com'",
            "blocked = (",
            "    'codex_rosetta',",
            "    'codex_rosetta.gateway.deepseek_responses_search',",
            "    'codex_rosetta._vendor.httpclient',",
            "    'codex_rosetta.gateway.transport.http.transport',",
            "    'codex_rosetta.observability.redaction',",
            "    'codex_rosetta.gateway.config',",
            "    'codex_rosetta.gateway.providers',",
            "    'deepseek_web_search_smoke',",
            ")",
            "assert not any(name in sys.modules for name in blocked)",
        ]
    )
    completed = subprocess.run(
        [sys.executable, "-c", probe],
        cwd=Path(__file__).parents[2],
        capture_output=True,
        text=True,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr


def _smoke_config(
    credential: str = "deepseek-smoke-secret", **overrides: object
) -> dict[str, Any]:
    row: dict[str, Any] = {
        "enabled": True,
        "provider": "deepseek",
        "base_url": "https://api.deepseek.com",
        "api_key": credential,
    }
    row.update(overrides)
    return {"providers": {"official-row": row}}


def _qualify_smoke(
    config: object,
    *,
    provider_id: object = "deepseek",
    query: object = "latest python release version",
    modes: object = ["direct"],
    max_upstream_calls: object = 1,
    calls: list[int] | None = None,
) -> QualifiedDeepSeekProvider:
    def load() -> object:
        if calls is not None:
            calls.append(1)
        return config

    return qualify_deepseek_provider(
        provider_id=provider_id,
        query=query,
        modes=modes,
        max_upstream_calls=max_upstream_calls,
        config_loader=load,
    )


def _smoke_error_text(error: BaseException) -> str:
    values: list[str] = [str(error), repr(error)]
    values.extend(repr(value) for value in error.args)
    traceback_obj = error.__traceback__
    while traceback_obj is not None:
        if traceback_obj.tb_frame.f_code.co_filename.endswith(
            "scripts/deepseek_web_search_smoke.py"
        ):
            values.extend(
                repr(value) for value in traceback_obj.tb_frame.f_locals.values()
            )
        traceback_obj = traceback_obj.tb_next
    return "\n".join(values)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("provider_id", "deepseek-other"),
        ("query", "latest python release version with secret"),
        ("modes", ["direct", "direct"]),
        ("max_upstream_calls", True),
    ],
)
def test_smoke_literal_controls_reject_before_config_loader(
    field: str, value: object
) -> None:
    calls: list[int] = []
    kwargs: dict[str, object] = {field: value}
    with pytest.raises(DeepSeekSmokeQualificationError) as caught:
        _qualify_smoke(_smoke_config(), calls=calls, **kwargs)
    assert calls == []
    assert str(caught.value) == "DeepSeek search smoke qualification failed"
    assert "latest python release version with secret" not in _smoke_error_text(
        caught.value
    )


@pytest.mark.parametrize(
    "config",
    [
        {"providers": []},
        {"providers": {"bad-name": []}},
        {"providers": {1: {}}},
        {"providers": {"row": {"provider": "deepseek"}}},
        _smoke_config(enabled="yes"),
        _smoke_config(provider="openai_chat"),
        _smoke_config(base_url="https://relay.example"),
        _smoke_config(api_key=""),
        _smoke_config(api_key="one,two"),
        _smoke_config(api_key="${DEEPSEEK_KEY}"),
    ],
)
def test_smoke_provider_qualification_fails_closed_without_echo(config: object) -> None:
    with pytest.raises(DeepSeekSmokeQualificationError) as caught:
        _qualify_smoke(config)
    assert str(caught.value) == "DeepSeek search smoke qualification failed"
    rendered = _smoke_error_text(caught.value)
    assert "deepseek-smoke-secret" not in rendered
    assert "latest python release version" not in rendered
    assert "relay.example" not in rendered


def test_smoke_provider_identity_requires_one_eligible_row_and_credential() -> None:
    config = {
        "providers": {
            "first": _smoke_config("first-secret")["providers"]["official-row"],
            "second": _smoke_config("second-secret")["providers"]["official-row"],
        }
    }
    with pytest.raises(DeepSeekSmokeQualificationError) as caught:
        _qualify_smoke(config)
    rendered = _smoke_error_text(caught.value)
    assert "first-secret" not in rendered
    assert "second-secret" not in rendered


def test_smoke_qualified_provider_is_opaque_but_retains_credential() -> None:
    credential = "deepseek-valid-secret"
    full_row = repr(_smoke_config(credential))
    result = _qualify_smoke(_smoke_config(credential))
    assert result.credential == credential
    assert result.provider_id == "deepseek"
    assert result.origin == "https://api.deepseek.com"
    assert repr(result) == "<QualifiedDeepSeekProvider>"
    assert str(result) == "<QualifiedDeepSeekProvider>"
    assert credential not in repr(result)
    assert full_row not in repr(result)
    assert result == result
    assert result != QualifiedDeepSeekProvider("other-secret")
    assert isinstance(hash(result), int)


@pytest.mark.parametrize("value", [True, False, 1.0, "1", None])
def test_smoke_call_budget_admission_accepts_only_exact_one(value: object) -> None:
    with pytest.raises(DeepSeekSmokeCallAdmissionError) as caught:
        CallAdmission(value)
    assert str(caught.value) == "DeepSeek search smoke call admission denied"


def test_smoke_call_budget_admission_allows_one_reservation_only() -> None:
    admission = CallAdmission(1)
    admission.reserve()
    with pytest.raises(DeepSeekSmokeCallAdmissionError) as caught:
        admission.reserve()
    assert str(caught.value) == "DeepSeek search smoke call admission denied"


def test_smoke_loader_exception_is_static_and_secret_free() -> None:
    secret = "loader-secret-value"

    def load() -> object:
        raise RuntimeError(secret)

    with pytest.raises(DeepSeekSmokeQualificationError) as caught:
        qualify_deepseek_provider(
            provider_id="deepseek",
            query="latest python release version",
            modes=["direct"],
            max_upstream_calls=1,
            config_loader=load,
        )
    assert caught.value.__cause__ is None
    assert caught.value.__context__ is None
    rendered = _smoke_error_text(caught.value)
    assert secret not in rendered
    assert "latest python release version" not in rendered


@pytest.mark.parametrize(
    "signal", [asyncio.CancelledError, KeyboardInterrupt, SystemExit, MemoryError]
)
def test_smoke_qualification_propagates_non_exception_signals(
    signal: type[BaseException],
) -> None:
    def load() -> object:
        raise signal("control-signal")

    with pytest.raises(signal):
        qualify_deepseek_provider(
            provider_id="deepseek",
            query="latest python release version",
            modes=["direct"],
            max_upstream_calls=1,
            config_loader=load,
        )


def test_smoke_import_surface_excludes_runtime_and_side_effects() -> None:
    module_path = Path(__file__).parents[2] / "scripts" / "deepseek_web_search_smoke.py"
    tree = ast.parse(module_path.read_text(encoding="utf-8"))
    imported = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(alias.name.split(".", 1)[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module.split(".", 1)[0])
    assert imported <= {
        "argparse",
        "asyncio",
        "collections",
        "deepseek_search_origin",
        "__future__",
        "hashlib",
        "importlib",
        "json",
        "pathlib",
        "sys",
        "types",
        "typing",
    }
    assert not any(
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id in {"open", "connect", "mkdir", "write_text"}
        for node in ast.walk(tree)
    )

    probe = "\n".join(
        [
            "import importlib.util",
            "import sys",
            "import types",
            f"path = {str(module_path)!r}",
            f"origin_path = {str(_PURE_ORIGIN_PATH)!r}",
            "sentinel = types.ModuleType('deepseek_search_origin')",
            "sentinel.DEEPSEEK_OFFICIAL_ORIGIN = 'sentinel-origin'",
            "def sentinel_normalize(value):",
            "    raise AssertionError('shadow origin must not be consumed')",
            "sentinel.normalize_deepseek_origin = sentinel_normalize",
            "sys.modules['deepseek_search_origin'] = sentinel",
            "modules_before = set(sys.modules)",
            "spec = importlib.util.spec_from_file_location('smoke_probe', path)",
            "assert spec is not None and spec.loader is not None",
            "module = importlib.util.module_from_spec(spec)",
            "spec.loader.exec_module(module)",
            "assert module._ORIGIN_CONTRACT is not sentinel",
            "assert module._OFFICIAL_ORIGIN == 'https://api.deepseek.com'",
            "assert sys.modules['deepseek_search_origin'] is sentinel",
            "assert sentinel.DEEPSEEK_OFFICIAL_ORIGIN == 'sentinel-origin'",
            "assert sentinel.normalize_deepseek_origin is sentinel_normalize",
            "assert not [",
            "    name for name, candidate in sys.modules.items()",
            "    if getattr(candidate, '__file__', None) == origin_path",
            "]",
            "assert not {",
            "    name for name in set(sys.modules) - modules_before",
            "    if 'deepseek' in name",
            "}",
            "blocked = (",
            "    'codex_rosetta.gateway.deepseek_responses_search',",
            "    'codex_rosetta._vendor.httpclient',",
            "    'codex_rosetta.gateway.transport.http.transport',",
            "    'codex_rosetta.observability.redaction',",
            "    'codex_rosetta.gateway.config',",
            "    'codex_rosetta.gateway.providers',",
            "    'deepseek_web_search_smoke',",
            ")",
            "assert not any(name in sys.modules for name in blocked)",
        ]
    )
    completed = subprocess.run(
        [sys.executable, "-c", probe],
        cwd=Path(__file__).parents[2],
        capture_output=True,
        text=True,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr


def _evidence_manifest() -> dict[str, Any]:
    digest = "a" * 64
    return {
        "schema": "codex-rosetta.deepseek-search-evidence",
        "version": 1,
        "mode": "direct",
        "status": "completed",
        "category": "success",
        "execution": {
            "provider_family": "DEEPSEEK_NATIVE_RESPONSES",
            "execution_mode": "NATIVE_RESPONSES_HOSTED_SEARCH",
            "model": "deepseek-v4-flash",
        },
        "provenance": {
            "implementation_generation": 2,
            "generation_2_live_proof": False,
            "generation_0_evidence": "referenced-only",
        },
        "hashes": {
            "request_sha256": digest,
            "query_sha256": "b" * 64,
            "result_sha256": "c" * 64,
        },
        "counts": {
            "upstream_calls": 1,
            "search_calls": 1,
            "result_count": 2,
            "citation_count": 2,
        },
        "latency_ms": 42,
        "usage": {"input_tokens": 12, "output_tokens": 8, "total_tokens": 20},
    }


def _evidence_error_text(error: BaseException) -> str:
    values = [str(error), repr(error), repr(error.args)]
    frame = error.__traceback__
    while frame is not None:
        if frame.tb_frame.f_code.co_filename == str(_EVIDENCE_PATH):
            values.extend(repr(value) for value in frame.tb_frame.f_locals.values())
        frame = frame.tb_next
    return "\n".join(values)


def test_evidence_schema_is_exact_and_deterministic() -> None:
    manifest = _evidence_manifest()
    first = serialize_evidence_manifest(manifest)
    second = serialize_evidence_manifest(dict(reversed(tuple(manifest.items()))))
    assert first == second
    assert (
        first
        == json.dumps(
            manifest,
            ensure_ascii=False,
            allow_nan=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode()
    )
    assert len(first) <= _EVIDENCE_MODULE.MAX_MANIFEST_BYTES


@pytest.mark.parametrize(
    "mutator",
    [
        lambda value: value.update({"unexpected": "opaque"}),
        lambda value: value["hashes"].update({"credential_sha256": "a" * 64}),
        lambda value: value["execution"].update({"response_id": "opaque"}),
        lambda value: value["hashes"].update({"query_sha256": "query text"}),
        lambda value: value["counts"].update({"result_count": True}),
        lambda value: value["usage"].update({"total_tokens": 21}),
        lambda value: value.update({"query": "raw query"}),
    ],
)
def test_evidence_schema_rejects_unknown_opaque_and_invalid_values(mutator) -> None:
    manifest = _evidence_manifest()
    mutator(manifest)
    with pytest.raises(DeepSeekEvidencePreparationError) as caught:
        serialize_evidence_manifest(manifest)
    assert str(caught.value) == "DeepSeek search evidence preparation failed"
    assert caught.value.__cause__ is None
    assert caught.value.__context__ is None


def test_evidence_preflight_returns_minimal_immutable_prepared_value() -> None:
    prepared = prepare_evidence_publication(
        _evidence_manifest(),
        "evidence/run-1",
        protected_tokens=("deepseek-secret",),
        protected_bodies=("raw response body",),
    )
    assert isinstance(prepared, PreparedEvidencePublication)
    assert prepared.directory == "evidence/run-1"
    assert prepared.final_path == "evidence/run-1/summary.json"
    assert prepared.manifest_bytes == serialize_evidence_manifest(_evidence_manifest())
    assert not hasattr(prepared, "__dict__")
    with pytest.raises(AttributeError):
        prepared.directory = "other"  # type: ignore[misc]
    assert repr(prepared) == "<PreparedEvidencePublication>"


@pytest.mark.parametrize(
    ("directory", "tokens", "bodies"),
    [
        ("evidence/run-1", ("completed",), ()),
        ("deepseek-secret-dir", ("safe-token",), ()),
        ("evidence/run-1", ("safe-token",), ("completed",)),
        ("evidence/run-1", ("safe-token",), ("summary.json",)),
        ("evidence/run-1", ("\ud800",), ()),
        ("evidence/run-1\x00", ("safe-token",), ()),
        ("evidence/run-1/", ("safe-token",), ()),
    ],
)
def test_evidence_preflight_collision_and_invalid_paths_are_zero_io(
    monkeypatch: pytest.MonkeyPatch,
    directory: str,
    tokens: tuple[str, ...],
    bodies: tuple[str, ...],
) -> None:
    calls: list[str] = []

    def fail_open(*args: Any, **kwargs: Any) -> Never:
        calls.append("open")
        raise AssertionError("filesystem operation")

    def fail_mkdir(*args: Any, **kwargs: Any) -> Never:
        calls.append("mkdir")
        raise AssertionError("filesystem operation")

    monkeypatch.setattr(builtins, "open", fail_open)
    monkeypatch.setattr(os, "mkdir", fail_mkdir)
    with pytest.raises(DeepSeekEvidencePreparationError):
        prepare_evidence_publication(
            _evidence_manifest(),
            directory,
            protected_tokens=tokens or ("safe-token",),
            protected_bodies=bodies,
        )
    assert calls == []


@pytest.mark.parametrize("helper", ["manifest", "scan", "serialize", "preflight"])
@pytest.mark.parametrize(
    "signal_type", [MemoryError, asyncio.CancelledError, KeyboardInterrupt, SystemExit]
)
def test_evidence_helpers_preserve_signal_identity_and_scrub_graph(
    monkeypatch: pytest.MonkeyPatch, helper: str, signal_type: type[BaseException]
) -> None:
    secret = "evidence-secret-token"
    failure = signal_type(secret)

    def explode(*args: object, **kwargs: object) -> Never:
        del args, kwargs
        raise failure

    target = {
        "manifest": "_keys_are_exact",
        "scan": "_encode_text",
        "serialize": "_json_dumps",
        "preflight": "_contains_collision",
    }[helper]
    monkeypatch.setattr(_EVIDENCE_MODULE, target, explode)
    with pytest.raises(signal_type) as caught:
        if helper == "manifest":
            _EVIDENCE_MODULE._manifest_is_allowed(_evidence_manifest())
        elif helper == "scan":
            _EVIDENCE_MODULE._encode_scan_values((secret,))
        elif helper == "serialize":
            serialize_evidence_manifest(_evidence_manifest())
        else:
            prepare_evidence_publication(
                _evidence_manifest(),
                "evidence/secret-path",
                protected_tokens=(secret,),
                protected_bodies=("body",),
            )
    assert caught.value is failure
    assert caught.value.args == ()
    assert caught.value.__cause__ is None
    assert caught.value.__context__ is None
    assert secret not in _evidence_error_text(caught.value)


def test_evidence_collision_second_cast_signal_scrubs_derived_locals(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    secret = "collision-secret"
    failure = RuntimeError(secret)
    calls = 0
    original_cast = _EVIDENCE_MODULE.cast

    def second_cast_signal(type_hint: object, value: object) -> object:
        nonlocal calls
        calls += 1
        if calls == 2:
            del type_hint, value
            raise failure
        return original_cast(type_hint, value)

    monkeypatch.setattr(_EVIDENCE_MODULE, "cast", second_cast_signal)
    with pytest.raises(RuntimeError) as caught:
        _EVIDENCE_MODULE._contains_collision(
            (b"manifest-collision-secret",), (b"protected-collision-secret",)
        )
    assert caught.value is failure
    assert caught.value.args == ()
    assert caught.value.__cause__ is None
    assert caught.value.__context__ is None
    rendered = _evidence_error_text(caught.value)
    assert secret not in rendered
    assert "manifest-collision-secret" not in rendered
    assert "protected-collision-secret" not in rendered


def test_evidence_writer_production_isolation() -> None:
    tree = ast.parse(_EVIDENCE_PATH.read_text(encoding="utf-8"))
    imported: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(alias.name.split(".", 1)[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module.split(".", 1)[0])
    assert imported <= {
        "__future__",
        "json",
        "os",
        "pathlib",
        "tempfile",
        "typing",
    }
    assert not imported & {
        "codex_rosetta",
        "asyncio",
        "httpx",
        "socket",
        "subprocess",
    }

    repository = Path(__file__).parents[2]
    helper_names = ("deepseek_search_evidence", "deepseek_web_search_smoke")
    assert not any(
        helper_name in path.read_text(encoding="utf-8")
        for path in (repository / "src").rglob("*.py")
        for helper_name in helper_names
    )

    configuration = tomllib.loads(
        (repository / "pyproject.toml").read_text(encoding="utf-8")
    )
    assert configuration["tool"]["setuptools"]["packages"]["find"]["where"] == ["src"]
    package_data = repr(configuration["tool"]["setuptools"].get("package-data", {}))
    project_scripts = repr(configuration["project"]["scripts"])
    assert not any(helper_name in package_data for helper_name in helper_names)
    assert not any(helper_name in project_scripts for helper_name in helper_names)

    with tempfile.TemporaryDirectory(
        prefix="codex-rosetta-wheel-isolation-", dir=repository.parent
    ) as temporary_directory:
        task_root = Path(temporary_directory).resolve()
        assert task_root.parent == repository.parent.resolve()
        assert task_root.name.startswith("codex-rosetta-wheel-isolation-")
        source_copy = task_root / "source"
        source_copy.mkdir()
        shutil.copy2(repository / "pyproject.toml", source_copy)
        shutil.copy2(repository / "README.md", source_copy)
        shutil.copy2(repository / "LICENSE", source_copy)
        shutil.copytree(
            repository / "src",
            source_copy / "src",
            ignore=shutil.ignore_patterns("__pycache__", "*.pyc"),
        )
        wheel_directory = task_root / "wheel"
        unpack_directory = task_root / "unpack"
        build_log = task_root / "build.log"
        completed = subprocess.run(
            [
                sys.executable,
                "-m",
                "build",
                "--wheel",
                "--no-isolation",
                "--outdir",
                str(wheel_directory),
            ],
            cwd=source_copy,
            capture_output=True,
            text=True,
            check=False,
        )
        build_log.write_text(completed.stdout + completed.stderr, encoding="utf-8")
        assert completed.returncode == 0, build_log.read_text(encoding="utf-8")
        wheels = tuple(wheel_directory.glob("*.whl"))
        assert len(wheels) == 1
        with zipfile.ZipFile(wheels[0]) as wheel:
            wheel_names = tuple(wheel.namelist())
            wheel.extractall(unpack_directory)
        assert not any(
            name.endswith(f"{helper_name}.py")
            for name in wheel_names
            for helper_name in helper_names
        )

        cleanup_targets = [
            wheel_directory,
            unpack_directory,
            source_copy / "build",
            *source_copy.glob("src/*.egg-info"),
            *source_copy.rglob("__pycache__"),
            *source_copy.rglob("*.pyc"),
        ]
        for target in cleanup_targets:
            resolved_target = target.resolve()
            assert resolved_target != task_root
            assert resolved_target.is_relative_to(task_root)
            if target.is_dir():
                shutil.rmtree(target)
            elif target.exists():
                target.unlink()
        assert build_log.is_file()
        assert not wheel_directory.exists()
        assert not unpack_directory.exists()
        assert not (source_copy / "build").exists()
        assert not tuple(source_copy.glob("src/*.egg-info"))
        assert not tuple(source_copy.rglob("__pycache__"))
        assert not tuple(source_copy.rglob("*.pyc"))


class _FaultingEvidenceFile:
    def __init__(self, wrapped: Any, stage: str) -> None:
        self._wrapped = wrapped
        self._stage = stage
        self._close_failed = False

    def write(self, value: bytes) -> int:
        if self._stage == "write":
            raise OSError("injected write failure")
        if self._stage == "short_write":
            partial = value[: max(1, len(value) // 2)]
            return self._wrapped.write(partial)
        return self._wrapped.write(value)

    def flush(self) -> None:
        if self._stage == "flush":
            raise OSError("injected flush failure")
        self._wrapped.flush()

    def fileno(self) -> int:
        return self._wrapped.fileno()

    def close(self) -> None:
        if self._stage == "close" and not self._close_failed:
            self._close_failed = True
            self._wrapped.close()
            raise OSError("injected close failure")
        self._wrapped.close()


def test_evidence_writer_writes_exact_private_random_publications(
    tmp_path: Path,
) -> None:
    manifest_bytes = serialize_evidence_manifest(_evidence_manifest())
    maximum_bytes = b"x" * _EVIDENCE_MODULE.MAX_MANIFEST_BYTES

    first = write_private_evidence_bytes(manifest_bytes, str(tmp_path))
    second = write_private_evidence_bytes(manifest_bytes, str(tmp_path))
    maximum = write_private_evidence_bytes(maximum_bytes, str(tmp_path))

    assert isinstance(first, Path)
    assert first.name == "summary.json"
    assert first.read_bytes() == manifest_bytes
    assert second.read_bytes() == manifest_bytes
    assert maximum.read_bytes() == maximum_bytes
    assert first.parent != second.parent
    assert first.parent.parent == tmp_path
    assert second.parent.parent == tmp_path
    assert stat.S_IMODE(first.parent.stat().st_mode) == 0o700
    assert stat.S_IMODE(first.stat().st_mode) == 0o600


class _BytesSubclass(bytes):
    pass


class _StrSubclass(str):
    pass


@pytest.mark.parametrize(
    ("manifest_bytes", "parent_factory"),
    [
        (bytearray(b"manifest"), lambda path: str(path)),
        (_BytesSubclass(b"manifest"), lambda path: str(path)),
        (b"", lambda path: str(path)),
        (b"x" * (_EVIDENCE_MODULE.MAX_MANIFEST_BYTES + 1), lambda path: str(path)),
        (b"manifest", lambda path: _StrSubclass(str(path))),
        (b"manifest", lambda path: ""),
        (b"manifest", lambda path: f"{path}\x00invalid"),
    ],
    ids=[
        "bytearray",
        "bytes-subclass",
        "empty-bytes",
        "oversized-bytes",
        "str-subclass",
        "empty-parent",
        "nul-parent",
    ],
)
def test_evidence_writer_rejects_invalid_input_before_directory_creation(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    manifest_bytes: object,
    parent_factory: Callable[[Path], object],
) -> None:
    calls: list[str] = []

    def unexpected_mkdtemp(*args: object, **kwargs: object) -> Never:
        del args, kwargs
        calls.append("mkdtemp")
        raise AssertionError("directory creation must not occur")

    monkeypatch.setattr(_EVIDENCE_MODULE.tempfile, "mkdtemp", unexpected_mkdtemp)
    with pytest.raises(DeepSeekEvidencePublicationError) as caught:
        write_private_evidence_bytes(
            cast(Any, manifest_bytes), cast(Any, parent_factory(tmp_path))
        )
    assert str(caught.value) == "DeepSeek search evidence publication failed"
    assert caught.value.__cause__ is None
    assert caught.value.__context__ is None
    assert calls == []


def test_atomic_publication_hides_final_until_same_directory_replace(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    manifest_bytes = serialize_evidence_manifest(_evidence_manifest())
    original_replace = _EVIDENCE_MODULE._replace_temp
    observations: list[tuple[Path, Path]] = []

    def observe_replace(temporary_path: Path, final_path: Path) -> None:
        assert temporary_path.parent == final_path.parent
        assert temporary_path.read_bytes() == manifest_bytes
        assert not final_path.exists()
        observations.append((temporary_path, final_path))
        original_replace(temporary_path, final_path)

    monkeypatch.setattr(_EVIDENCE_MODULE, "_replace_temp", observe_replace)
    final_path = write_private_evidence_bytes(manifest_bytes, str(tmp_path))
    assert observations == [(observations[0][0], final_path)]
    assert final_path.read_bytes() == manifest_bytes


@pytest.mark.parametrize(
    "stage", ["open", "write", "short_write", "flush", "file_fsync", "close", "replace"]
)
def test_evidence_writer_ordinary_failure_is_static_and_cleans_owned_paths(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, stage: str
) -> None:
    manifest_bytes = serialize_evidence_manifest(_evidence_manifest())
    original_open = _EVIDENCE_MODULE._open_temp_file

    def open_with_failure(file_descriptor: int):
        if stage == "open":
            raise OSError("injected open failure")
        return _FaultingEvidenceFile(original_open(file_descriptor), stage)

    monkeypatch.setattr(_EVIDENCE_MODULE, "_open_temp_file", open_with_failure)
    if stage == "file_fsync":
        monkeypatch.setattr(
            _EVIDENCE_MODULE,
            "_fsync_temp_file",
            lambda stream: (_ for _ in ()).throw(OSError("injected fsync failure")),
        )
    if stage == "replace":
        monkeypatch.setattr(
            _EVIDENCE_MODULE,
            "_replace_temp",
            lambda temporary_path, final_path: (_ for _ in ()).throw(
                OSError("injected replace failure")
            ),
        )

    with pytest.raises(DeepSeekEvidencePublicationError) as caught:
        write_private_evidence_bytes(manifest_bytes, str(tmp_path))
    assert str(caught.value) == "DeepSeek search evidence publication failed"
    assert caught.value.__cause__ is None
    assert caught.value.__context__ is None
    assert tuple(tmp_path.iterdir()) == ()


class _SyntheticEvidenceSignal(BaseException):
    pass


@pytest.mark.parametrize(
    "failure",
    [
        KeyboardInterrupt("control"),
        SystemExit("control"),
        asyncio.CancelledError("control"),
        MemoryError("resource"),
        _SyntheticEvidenceSignal("control"),
    ],
)
def test_evidence_writer_control_signal_identity_and_cleanup(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, failure: BaseException
) -> None:
    manifest_bytes = serialize_evidence_manifest(_evidence_manifest())

    def raise_signal(temporary_path: Path, final_path: Path) -> Never:
        del temporary_path, final_path
        raise failure

    monkeypatch.setattr(_EVIDENCE_MODULE, "_replace_temp", raise_signal)
    with pytest.raises(type(failure)) as caught:
        write_private_evidence_bytes(manifest_bytes, str(tmp_path))
    assert caught.value is failure
    assert tuple(tmp_path.iterdir()) == ()


class _OfflineHarnessResult:
    __slots__ = ("output", "results", "usage")

    def __init__(self) -> None:
        self.output = "Python 3.14.7 is the latest stable release."
        self.results = (
            {
                "title": "Python 3.14.7",
                "url": "https://www.python.org/downloads/release/python-3147/",
                "snippet": "Python 3.14.7 release page",
            },
            {
                "title": "Python downloads",
                "url": "https://www.python.org/downloads/",
                "snippet": "Official Python downloads",
            },
        )
        self.usage = {"input_tokens": 12, "output_tokens": 8, "total_tokens": 20}


class _OfflineHarnessClient:
    def __init__(
        self,
        events: list[str],
        *,
        failure: BaseException | None = None,
    ) -> None:
        self.events = events
        self.failure = failure
        self.calls: list[tuple[object, object, object, object]] = []

    async def execute(
        self,
        query: object,
        *,
        model: object,
        max_output_tokens: object,
        citation_limit: object,
    ) -> _OfflineHarnessResult:
        self.events.append("execute")
        self.calls.append((query, model, max_output_tokens, citation_limit))
        if self.failure is not None:
            raise self.failure
        return _OfflineHarnessResult()


@pytest.mark.asyncio
async def test_harness_composition_happy_path_is_ordered_single_call_and_sanitized(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    events: list[str] = []
    factory_inputs: list[tuple[str, str]] = []
    writer_inputs: list[tuple[bytes, str]] = []
    client = _OfflineHarnessClient(events)
    original_qualify = _SMOKE_MODULE.qualify_deepseek_provider
    original_admission = _SMOKE_MODULE.CallAdmission
    original_prepare = _SMOKE_MODULE.prepare_evidence_publication
    original_write = _SMOKE_MODULE.write_private_evidence_bytes

    def qualify(**kwargs: object) -> QualifiedDeepSeekProvider:
        events.append("qualification")
        return original_qualify(**kwargs)

    class RecordingAdmission:
        def __init__(self, maximum: object) -> None:
            events.append("admission")
            self.delegate = original_admission(maximum)

        def reserve(self) -> None:
            events.append("reserve")
            self.delegate.reserve()

    def factory(credential: str, origin: str) -> _OfflineHarnessClient:
        events.append("client_factory")
        factory_inputs.append((credential, origin))
        return client

    def prepare(*args: object, **kwargs: object) -> PreparedEvidencePublication:
        events.append("prepare")
        return original_prepare(*args, **kwargs)

    def write(manifest_bytes: bytes, trusted_parent: str) -> Path:
        events.append("write")
        writer_inputs.append((manifest_bytes, trusted_parent))
        return original_write(manifest_bytes, trusted_parent)

    monkeypatch.setattr(_SMOKE_MODULE, "qualify_deepseek_provider", qualify)
    monkeypatch.setattr(_SMOKE_MODULE, "CallAdmission", RecordingAdmission)
    monkeypatch.setattr(_SMOKE_MODULE, "prepare_evidence_publication", prepare)
    monkeypatch.setattr(_SMOKE_MODULE, "write_private_evidence_bytes", write)

    final_path = await run_offline_deepseek_search_harness(
        config_loader=lambda: _smoke_config("offline-fake-credential"),
        client_factory=factory,
        trusted_parent=str(tmp_path),
    )

    assert events == [
        "qualification",
        "admission",
        "reserve",
        "client_factory",
        "execute",
        "prepare",
        "write",
    ]
    assert factory_inputs == [("offline-fake-credential", "https://api.deepseek.com")]
    assert client.calls == [
        ("latest python release version", "deepseek-v4-flash", 1024, 5)
    ]
    assert len(writer_inputs) == 1
    manifest_bytes, parent = writer_inputs[0]
    assert type(manifest_bytes) is bytes
    assert parent == str(tmp_path)
    assert final_path.read_bytes() == manifest_bytes
    manifest = json.loads(manifest_bytes)
    assert manifest["counts"] == {
        "citation_count": 2,
        "result_count": 2,
        "search_calls": 1,
        "upstream_calls": 1,
    }
    assert manifest["provenance"] == {
        "generation_0_evidence": "referenced-only",
        "generation_2_live_proof": False,
        "implementation_generation": 2,
    }
    assert manifest["usage"] == {
        "input_tokens": 12,
        "output_tokens": 8,
        "total_tokens": 20,
    }
    assert b"offline-fake-credential" not in manifest_bytes
    assert b"latest python release version" not in manifest_bytes
    assert b"Python 3.14.7 is the latest stable release" not in manifest_bytes
    assert b"python.org" not in manifest_bytes


@pytest.mark.asyncio
async def test_harness_composition_qualification_failure_has_zero_effects(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    effects: list[str] = []

    def unexpected_factory(credential: str, origin: str) -> Never:
        del credential, origin
        effects.append("client")
        raise AssertionError("client must not be constructed")

    class UnexpectedAdmission:
        def __init__(self, maximum: object) -> None:
            del maximum
            effects.append("admission")

    monkeypatch.setattr(_SMOKE_MODULE, "CallAdmission", UnexpectedAdmission)
    monkeypatch.setattr(
        _SMOKE_MODULE,
        "prepare_evidence_publication",
        lambda *args, **kwargs: effects.append("prepare"),
    )
    monkeypatch.setattr(
        _SMOKE_MODULE,
        "write_private_evidence_bytes",
        lambda *args, **kwargs: effects.append("write"),
    )

    with pytest.raises(DeepSeekOfflineHarnessError) as caught:
        await run_offline_deepseek_search_harness(
            config_loader=lambda: {"providers": {}},
            client_factory=unexpected_factory,
            trusted_parent=str(tmp_path),
        )
    assert str(caught.value) == "DeepSeek offline search harness failed"
    assert repr(caught.value) == "DeepSeekOfflineHarnessError()"
    assert effects == []
    assert tuple(tmp_path.iterdir()) == ()


@pytest.mark.asyncio
@pytest.mark.parametrize("failure_stage", ["factory", "client", "prepare", "writer"])
async def test_harness_composition_ordinary_failure_is_static_and_never_retries(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    failure_stage: str,
) -> None:
    events: list[str] = []
    original_admission = _SMOKE_MODULE.CallAdmission

    class RecordingAdmission:
        def __init__(self, maximum: object) -> None:
            events.append("admission")
            self.delegate = original_admission(maximum)

        def reserve(self) -> None:
            events.append("reserve")
            self.delegate.reserve()

    client = _OfflineHarnessClient(
        events,
        failure=RuntimeError("fake client body") if failure_stage == "client" else None,
    )

    def factory(credential: str, origin: str) -> _OfflineHarnessClient:
        del credential, origin
        events.append("client_factory")
        if failure_stage == "factory":
            raise RuntimeError("fake factory body")
        return client

    original_prepare = _SMOKE_MODULE.prepare_evidence_publication

    def prepare(*args: object, **kwargs: object) -> PreparedEvidencePublication:
        events.append("prepare")
        if failure_stage == "prepare":
            raise ValueError("synthetic result body")
        return original_prepare(*args, **kwargs)

    def write(manifest_bytes: bytes, trusted_parent: str) -> Path:
        del manifest_bytes, trusted_parent
        events.append("write")
        raise OSError("synthetic path")

    monkeypatch.setattr(_SMOKE_MODULE, "CallAdmission", RecordingAdmission)
    monkeypatch.setattr(_SMOKE_MODULE, "prepare_evidence_publication", prepare)
    monkeypatch.setattr(_SMOKE_MODULE, "write_private_evidence_bytes", write)

    with pytest.raises(DeepSeekOfflineHarnessError) as caught:
        await run_offline_deepseek_search_harness(
            config_loader=lambda: _smoke_config(),
            client_factory=factory,
            trusted_parent=str(tmp_path),
        )
    assert str(caught.value) == "DeepSeek offline search harness failed"
    assert caught.value.__cause__ is None
    assert events.count("reserve") == 1
    assert events.count("client_factory") == 1
    assert events.count("execute") == (0 if failure_stage == "factory" else 1)
    assert events.count("prepare") == (
        0 if failure_stage in {"factory", "client"} else 1
    )
    assert events.count("write") == (1 if failure_stage == "writer" else 0)
    assert tuple(tmp_path.iterdir()) == ()


class _OfflineHarnessControlSignal(BaseException):
    pass


@pytest.mark.asyncio
@pytest.mark.parametrize("stage", ["qualification", "client", "prepare", "writer"])
@pytest.mark.parametrize(
    "signal_type",
    [
        asyncio.CancelledError,
        KeyboardInterrupt,
        SystemExit,
        MemoryError,
        _OfflineHarnessControlSignal,
    ],
)
async def test_harness_composition_cancellation_and_resource_signals_preserve_identity(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    stage: str,
    signal_type: type[BaseException],
) -> None:
    signal = signal_type("control")
    events: list[str] = []
    client = _OfflineHarnessClient(
        events, failure=signal if stage == "client" else None
    )

    def config_loader() -> object:
        events.append("qualification")
        if stage == "qualification":
            raise signal
        return _smoke_config()

    def factory(credential: str, origin: str) -> _OfflineHarnessClient:
        del credential, origin
        events.append("client_factory")
        return client

    original_prepare = _SMOKE_MODULE.prepare_evidence_publication

    def prepare(*args: object, **kwargs: object) -> PreparedEvidencePublication:
        events.append("prepare")
        if stage == "prepare":
            raise signal
        return original_prepare(*args, **kwargs)

    def write(manifest_bytes: bytes, trusted_parent: str) -> Path:
        del manifest_bytes, trusted_parent
        events.append("write")
        raise signal

    monkeypatch.setattr(_SMOKE_MODULE, "prepare_evidence_publication", prepare)
    monkeypatch.setattr(_SMOKE_MODULE, "write_private_evidence_bytes", write)

    with pytest.raises(signal_type) as caught:
        await run_offline_deepseek_search_harness(
            config_loader=config_loader,
            client_factory=factory,
            trusted_parent=str(tmp_path),
        )
    assert caught.value is signal
    assert events.count("client_factory") == (0 if stage == "qualification" else 1)
    assert events.count("execute") == (0 if stage == "qualification" else 1)
    assert events.count("prepare") == (1 if stage in {"prepare", "writer"} else 0)
    assert events.count("write") == (1 if stage == "writer" else 0)
    assert tuple(tmp_path.iterdir()) == ()


@pytest.mark.asyncio
async def test_harness_composition_network_guard_keeps_path_offline(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    import socket

    events: list[str] = []
    client = _OfflineHarnessClient(events)

    def blocked(*args: object, **kwargs: object) -> Never:
        del args, kwargs
        raise AssertionError("network or process access is forbidden")

    monkeypatch.setattr(socket, "socket", blocked)
    monkeypatch.setattr(asyncio, "create_subprocess_exec", blocked)
    monkeypatch.setattr(asyncio, "create_subprocess_shell", blocked)

    final_path = await run_offline_deepseek_search_harness(
        config_loader=lambda: _smoke_config(),
        client_factory=lambda credential, origin: client,
        trusted_parent=str(tmp_path),
    )
    assert final_path.is_file()
    assert events == ["execute"]


def test_smoke_cli_runs_only_explicit_offline_fake_path(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    exit_code = _SMOKE_MODULE.main(
        ["--offline-fake", "--evidence-parent", str(tmp_path)]
    )
    captured = capsys.readouterr()
    assert exit_code == 0
    assert captured.err == ""
    lines = captured.out.splitlines()
    assert len(lines) == 1
    assert Path(lines[0]).is_file()
    assert Path(lines[0]).parent.parent == tmp_path


@pytest.mark.parametrize(
    "unsupported",
    ["--config", "--api-key", "--query", "--origin", "--url", "--live", "--port"],
)
def test_smoke_cli_rejects_runtime_and_live_options_before_composition(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, unsupported: str
) -> None:
    calls: list[str] = []

    async def unexpected(**kwargs: object) -> Never:
        del kwargs
        calls.append("composition")
        raise AssertionError("composition must not run")

    monkeypatch.setattr(
        _SMOKE_MODULE, "run_offline_deepseek_search_harness", unexpected
    )
    with pytest.raises(SystemExit):
        _SMOKE_MODULE.main(
            [
                "--offline-fake",
                "--evidence-parent",
                str(tmp_path),
                unsupported,
                "value",
            ]
        )
    assert calls == []
