"""Focused proportional tests for the DeepSeek hosted-search seams."""

from __future__ import annotations

import asyncio
import importlib.util
import json
import stat
from pathlib import Path

import pytest

import codex_rosetta.gateway.deepseek_responses_search as adapter
from codex_rosetta.gateway.transport.http.transport import BoundedHttpResponse

ROOT = Path(__file__).parents[2]


def _load_script(name: str):
    path = ROOT / "scripts" / name
    spec = importlib.util.spec_from_file_location(name.replace(".py", ""), path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _response() -> dict[str, object]:
    return {
        "status": "completed",
        "output": [
            {"type": "reasoning", "status": "completed"},
            {"type": "web_search_call", "status": "completed"},
            {
                "type": "message",
                "content": [
                    {
                        "type": "output_text",
                        "text": "  Answer from the web. ",
                        "annotations": [
                            {
                                "type": "url_citation",
                                "url": "HTTPS://Example.com:443/docs#frag",
                                "title": " Example docs ",
                                "start_index": 2,
                                "end_index": 12,
                            }
                        ],
                    }
                ],
            },
        ],
        "usage": {"input_tokens": 4, "output_tokens": 6, "total_tokens": 10},
    }


def _request(**overrides: object) -> adapter.DeepSeekResponsesSearchRequest:
    values = {
        "query": " latest python release ",
        "origin": adapter.DEEPSEEK_RESPONSES_OFFICIAL_ORIGIN,
        "model": adapter.DEEPSEEK_RESPONSES_SEARCH_MODEL,
        "max_output_tokens": 1024,
        "citation_limit": 5,
        "timeout": 5,
    }
    values.update(overrides)
    return adapter.build_deepseek_responses_search_request(**values)


def test_request_is_exact_allowlist() -> None:
    request = _request()
    assert request.origin == adapter.DEEPSEEK_RESPONSES_OFFICIAL_ORIGIN
    assert request.body == {
        "model": "deepseek-v4-flash",
        "input": "Search the web for the following query. Return a concise factual answer and cite the sources you used.\n\nQuery: latest python release",
        "tools": [{"type": "web_search"}],
        "tool_choice": {"type": "web_search"},
        "max_output_tokens": 1024,
    }


@pytest.mark.parametrize(
    "origin",
    [
        "http://api.deepseek.com",
        "https://relay.example",
        "https://api.deepseek.com/v1",
        "https://api.deepseek.com:8443",
        "https://user:pass@api.deepseek.com",
    ],
)
def test_origin_rejects_non_official(origin: str) -> None:
    with pytest.raises(ValueError):
        adapter.normalize_deepseek_responses_origin(origin)


def test_origin_accepts_case_and_default_port() -> None:
    assert (
        adapter.normalize_deepseek_responses_origin("HTTPS://API.DEEPSEEK.COM:443/")
        == adapter.DEEPSEEK_RESPONSES_OFFICIAL_ORIGIN
    )


@pytest.mark.parametrize(
    "field,value",
    [
        ("query", ""),
        ("model", "deepseek-v4-pro"),
        ("max_output_tokens", 256),
        ("citation_limit", 0),
        ("timeout", 0),
        ("timeout", 10**400),
    ],
)
def test_local_controls_fail_before_http(field: str, value: object) -> None:
    with pytest.raises(ValueError):
        _request(**{field: value})


def test_response_normalization_and_bounds() -> None:
    result = adapter.parse_deepseek_responses_search_response(
        _response(), citation_limit=5
    )
    assert result["output"] == "Answer from the web."
    assert result["results"] == [
        {
            "title": "Example docs",
            "url": "https://example.com/docs",
            "content": "Answer fro",
        }
    ]
    assert result["usage"] == {
        "input_tokens": 4,
        "output_tokens": 6,
        "total_tokens": 10,
    }


@pytest.mark.parametrize(
    "value",
    [
        {"status": "incomplete"},
        {"status": "completed", "output": []},
        {
            "status": "completed",
            "output": [{"type": "web_search_call", "status": "completed"}],
        },
    ],
)
def test_invalid_response_fails_closed(value: object) -> None:
    with pytest.raises(adapter.DeepSeekResponsesSearchParseError):
        adapter.parse_deepseek_responses_search_response(value, citation_limit=5)


class _FakeAsyncClient:
    def __init__(self, **kwargs: object) -> None:
        self.kwargs = kwargs

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_args: object) -> None:
        return None


def test_client_performs_one_bounded_request(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[dict[str, object]] = []
    monkeypatch.setattr(adapter, "AsyncClient", _FakeAsyncClient)

    async def request(
        _client: object, _method: str, _url: str, **kwargs: object
    ) -> BoundedHttpResponse:
        calls.append(kwargs)
        return BoundedHttpResponse(200, {}, json.dumps(_response()).encode())

    monkeypatch.setattr(adapter, "request_bounded_response", request)
    result = asyncio.run(adapter.DeepSeekResponsesSearchClient("secret").execute("q"))
    assert result.output == "Answer from the web."
    assert len(calls) == 1
    assert (
        calls[0]["max_success_bytes"]
        == adapter.DEEPSEEK_RESPONSES_SEARCH_RESPONSE_MAX_BYTES
    )


def test_client_maps_http_and_cancellation(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(adapter, "AsyncClient", _FakeAsyncClient)

    async def request(*_args: object, **_kwargs: object) -> BoundedHttpResponse:
        return BoundedHttpResponse(503, {}, b"upstream-private")

    monkeypatch.setattr(adapter, "request_bounded_response", request)
    with pytest.raises(adapter.DeepSeekSearchError) as caught:
        asyncio.run(adapter.DeepSeekResponsesSearchClient("secret").search("q"))
    assert caught.value.category is adapter.DeepSeekSearchErrorCategory.HTTP_ERROR
    assert str(caught.value) == "http_error"

    async def cancelled(*_args: object, **_kwargs: object) -> BoundedHttpResponse:
        raise asyncio.CancelledError

    monkeypatch.setattr(adapter, "request_bounded_response", cancelled)
    with pytest.raises(asyncio.CancelledError):
        asyncio.run(adapter.DeepSeekResponsesSearchClient("secret").search("q"))


def test_origin_script_is_import_inert() -> None:
    origin = _load_script("deepseek_search_origin.py")
    assert (
        origin.normalize_deepseek_origin("https://api.deepseek.com")
        == "https://api.deepseek.com"
    )
    assert not any(name.startswith("codex_rosetta") for name in origin.__dict__)


def test_evidence_writer_is_private_atomic_and_static(tmp_path: Path) -> None:
    evidence = _load_script("deepseek_search_evidence.py")
    payload = evidence.serialize_evidence_manifest({"status": "completed", "value": 1})
    output = evidence.write_private_evidence_bytes(payload, str(tmp_path))
    assert output.read_bytes() == payload
    assert stat.S_IMODE(output.parent.stat().st_mode) == 0o700
    assert stat.S_IMODE(output.stat().st_mode) == 0o600
    with pytest.raises(evidence.DeepSeekEvidencePublicationError):
        evidence.write_private_evidence_bytes(b"", str(tmp_path))
