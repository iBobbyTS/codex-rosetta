"""OR-S01.1-CONTROL-WIRE: pure DeepSeek request/control contract tests."""

from __future__ import annotations

import ast
import inspect
import json
import random
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
from codex_rosetta.observability.redaction import SecretRedactor

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


def test_pre_io_module_has_no_forbidden_runtime_dependency_or_parameter() -> None:
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
        "asyncio",
        "http.client",
        "httpx",
        "os",
        "pathlib",
        "socket",
        "urllib.request",
        "codex_rosetta.gateway.config",
        "codex_rosetta.gateway.providers",
        "codex_rosetta.gateway.transport",
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


def test_parser_module_remains_pure_and_has_no_production_importer() -> None:
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
            "asyncio",
            "http.client",
            "httpx",
            "json",
            "os",
            "pathlib",
            "socket",
            "urllib.request",
            "codex_rosetta.gateway.config",
            "codex_rosetta.gateway.providers",
            "codex_rosetta.gateway.transport",
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
