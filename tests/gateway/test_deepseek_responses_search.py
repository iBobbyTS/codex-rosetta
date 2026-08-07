"""OR-S01.1-CONTROL-WIRE: pure DeepSeek request/control contract tests."""

from __future__ import annotations

import ast
import inspect
from collections.abc import Callable
from pathlib import Path
from typing import Any, Never, cast

import pytest

from codex_rosetta.gateway.deepseek_responses_search import (
    DEEPSEEK_RESPONSES_OFFICIAL_ORIGIN,
    DEEPSEEK_RESPONSES_SEARCH_MODEL,
    DeepSeekResponsesSearchRequest,
    build_deepseek_responses_search_request,
    normalize_deepseek_responses_origin,
)

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
        "codex_rosetta.observability.redaction",
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
