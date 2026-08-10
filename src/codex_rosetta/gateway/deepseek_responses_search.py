"""Bounded DeepSeek Responses hosted-search adapter.

The adapter deliberately keeps a small, provider-specific contract: validate the
official origin and request controls, perform one bounded HTTP request, and
normalize the documented response shape for the existing search executor.
"""

from __future__ import annotations

import asyncio
import json
import math
from dataclasses import dataclass
from enum import StrEnum
from typing import Any, cast
from urllib.parse import urlsplit, urlunsplit

from codex_rosetta._vendor.httpclient import AsyncClient, HttpTimeoutError
from .transport._base import (
    UpstreamConnectionError,
    UpstreamNetworkError,
    UpstreamResponseTooLargeError,
)
from .transport.http.transport import BoundedHttpResponse, request_bounded_response

DEEPSEEK_RESPONSES_OFFICIAL_ORIGIN = "https://api.deepseek.com"
DEEPSEEK_RESPONSES_SEARCH_MODEL = "deepseek-v4-flash"
DEEPSEEK_RESPONSES_SEARCH_TOKEN_LIMITS = frozenset({512, 1024, 1536})
DEEPSEEK_RESPONSES_SEARCH_RESPONSE_MAX_BYTES = 4 * 1024 * 1024
DEFAULT_DEEPSEEK_RESPONSES_SEARCH_TIMEOUT = 120.0
DEFAULT_DEEPSEEK_RESPONSES_SEARCH_MAX_OUTPUT_TOKENS = 1024
DEFAULT_DEEPSEEK_RESPONSES_SEARCH_CITATION_LIMIT = 5

_QUERY_MAX_LENGTH = 4_000
_MAX_ITEMS = 256
_OUTPUT_MAX_LENGTH = 64_000
_TITLE_MAX_LENGTH = 500
_URL_MAX_LENGTH = 8_192
_CONTENT_MAX_LENGTH = 1_200
_USAGE_TOKEN_MAX = 1_000_000_000
_SEARCH_PROMPT_PREFIX = (
    "Search the web for the following query. Return a concise factual answer and "
    "cite the sources you used.\n\nQuery: "
)


class DeepSeekResponsesSearchParseError(ValueError):
    """Static provider-neutral failure for an invalid hosted-search response."""

    def __init__(self) -> None:
        super().__init__("DeepSeek Responses search response is invalid")


class DeepSeekSearchErrorCategory(StrEnum):
    """Stable categories consumed by the existing search-chain owner."""

    CONNECTION_ERROR = "connection_error"
    TRANSPORT_ERROR = "transport_error"
    TIMEOUT = "timeout"
    HTTP_ERROR = "http_error"
    INVALID_JSON = "invalid_json"
    INVALID_SHAPE = "invalid_shape"
    BODY_LIMIT = "body_limit"
    RESPONSE_TOO_LARGE = "body_limit"
    # Retained as a wire-compatible category for the existing executor's
    # exhaustive mapping; this adapter no longer performs collision detection.
    CREDENTIAL_COLLISION = "credential_collision"


class DeepSeekSearchError(RuntimeError):
    """Bounded DeepSeek adapter error without upstream text or credentials."""

    def __init__(
        self, category: DeepSeekSearchErrorCategory, *, status_code: int | None = None
    ) -> None:
        self.category = category
        self.status_code = (
            status_code
            if type(status_code) is int and 100 <= status_code <= 599
            else None
        )
        super().__init__(category.value)


def normalize_deepseek_responses_origin(origin: object) -> str:
    """Validate an official DeepSeek HTTPS root and return its canonical value."""
    if (
        type(origin) is not str
        or not origin
        or origin != origin.strip()
        or any(ord(c) < 0x20 for c in origin)
    ):
        raise ValueError("DeepSeek Responses origin must be the official HTTPS root")
    try:
        parsed = urlsplit(origin)
        port = parsed.port
    except ValueError:
        raise ValueError(
            "DeepSeek Responses origin must be the official HTTPS root"
        ) from None
    if (
        parsed.scheme.lower() != "https"
        or (parsed.hostname or "").lower() != "api.deepseek.com"
        or parsed.netloc.lower() not in {"api.deepseek.com", "api.deepseek.com:443"}
        or port not in (None, 443)
        or parsed.username is not None
        or parsed.password is not None
        or parsed.path not in ("", "/")
        or parsed.query
        or parsed.fragment
    ):
        raise ValueError("DeepSeek Responses origin must be the official HTTPS root")
    return DEEPSEEK_RESPONSES_OFFICIAL_ORIGIN


def _normalize_query(query: object) -> str:
    if type(query) is not str:
        raise ValueError("DeepSeek Responses search query must be a string")
    query = query.strip()
    if not 1 <= len(query) <= _QUERY_MAX_LENGTH:
        raise ValueError(
            "DeepSeek Responses search query length must be from 1 to 4000"
        )
    return query


def _validate_model(model: object) -> str:
    if type(model) is not str or model != DEEPSEEK_RESPONSES_SEARCH_MODEL:
        raise ValueError("DeepSeek Responses search model is not supported")
    return model


def _validate_max_output_tokens(value: object) -> int:
    if type(value) is not int or value not in DEEPSEEK_RESPONSES_SEARCH_TOKEN_LIMITS:
        raise ValueError("DeepSeek Responses max_output_tokens is not supported")
    return value


def _validate_citation_limit(value: object) -> int:
    if type(value) is not int or not 1 <= value <= 8:
        raise ValueError("DeepSeek Responses citation_limit must be from 1 to 8")
    return value


def _normalize_timeout(value: object) -> float:
    if type(value) not in (int, float) or isinstance(value, bool):
        raise ValueError("DeepSeek Responses timeout must be a finite positive number")
    normalized = float(cast(int | float, value))
    if not math.isfinite(normalized) or normalized <= 0:
        raise ValueError("DeepSeek Responses timeout must be a finite positive number")
    return normalized


@dataclass(frozen=True, slots=True)
class DeepSeekResponsesSearchRequest:
    """Validated inert request value for one hosted search."""

    origin: str
    model: str
    query: str
    max_output_tokens: int
    citation_limit: int
    timeout: float

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "origin", normalize_deepseek_responses_origin(self.origin)
        )
        object.__setattr__(self, "model", _validate_model(self.model))
        object.__setattr__(self, "query", _normalize_query(self.query))
        object.__setattr__(
            self,
            "max_output_tokens",
            _validate_max_output_tokens(self.max_output_tokens),
        )
        object.__setattr__(
            self, "citation_limit", _validate_citation_limit(self.citation_limit)
        )
        object.__setattr__(self, "timeout", _normalize_timeout(self.timeout))

    @property
    def body(self) -> dict[str, object]:
        """Return the exact five-field allowlisted Responses request body."""
        return {
            "model": self.model,
            "input": f"{_SEARCH_PROMPT_PREFIX}{self.query}",
            "tools": [{"type": "web_search"}],
            "tool_choice": {"type": "web_search"},
            "max_output_tokens": self.max_output_tokens,
        }


def build_deepseek_responses_search_request(
    *,
    query: object,
    origin: object,
    model: object,
    max_output_tokens: object,
    citation_limit: object,
    timeout: object,
) -> DeepSeekResponsesSearchRequest:
    """Validate controls and build one inert hosted-search request."""
    return DeepSeekResponsesSearchRequest(
        origin=cast(str, origin),
        model=cast(str, model),
        query=cast(str, query),
        max_output_tokens=cast(int, max_output_tokens),
        citation_limit=cast(int, citation_limit),
        timeout=cast(int | float, timeout),
    )


def _as_dict(value: object) -> dict[str, Any]:
    if type(value) is not dict or len(value) > _MAX_ITEMS:
        raise DeepSeekResponsesSearchParseError
    return cast(dict[str, Any], value)


def _as_list(value: object) -> list[Any]:
    if type(value) is not list or len(value) > _MAX_ITEMS:
        raise DeepSeekResponsesSearchParseError
    return value


def _canonical_url(value: object) -> tuple[str, str] | None:
    if (
        type(value) is not str
        or not value
        or len(value) > _URL_MAX_LENGTH
        or any(c.isspace() for c in value)
    ):
        return None
    try:
        parsed = urlsplit(value)
        port = parsed.port
    except ValueError:
        return None
    hostname = (parsed.hostname or "").lower().rstrip(".")
    if (
        parsed.scheme.lower() not in {"http", "https"}
        or not hostname
        or parsed.username
        or parsed.password
    ):
        return None
    netloc = hostname
    if port is not None and not (
        (parsed.scheme.lower() == "http" and port == 80)
        or (parsed.scheme.lower() == "https" and port == 443)
    ):
        netloc += f":{port}"
    canonical = urlunsplit(
        (parsed.scheme.lower(), netloc, parsed.path or "/", parsed.query, "")
    )
    return (canonical, hostname) if len(canonical) <= _URL_MAX_LENGTH else None


def _bounded_text(value: object, limit: int) -> str:
    if type(value) is not str:
        return ""
    text = " ".join(value.split())
    return text if len(text) <= limit else text[: limit - 3].rstrip() + "..."


def _citation_content(text: str, annotation: dict[str, Any]) -> str:
    start, end = annotation.get("start_index"), annotation.get("end_index")
    if (
        type(start) is not int
        or type(end) is not int
        or start < 0
        or end < start
        or end > len(text)
    ):
        return ""
    return text[start : min(end, start + _CONTENT_MAX_LENGTH)]


def _parse_output_items(
    output_items: list[Any], limit: int
) -> tuple[bool, list[str], list[dict[str, str]]]:
    searched = False
    fragments: list[str] = []
    results: list[dict[str, str]] = []
    seen: set[str] = set()
    for item in output_items:
        if type(item) is not dict:
            continue
        kind = item.get("type")
        if kind == "web_search_call":
            searched = searched or item.get("status") == "completed"
        elif kind == "message":
            for part in _as_list(item.get("content")):
                if type(part) is not dict or part.get("type") != "output_text":
                    continue
                text = part.get("text")
                if type(text) is not str or not text.strip():
                    raise DeepSeekResponsesSearchParseError
                if sum(map(len, fragments)) + len(text) > _OUTPUT_MAX_LENGTH:
                    raise DeepSeekResponsesSearchParseError
                fragments.append(text)
                for annotation in _as_list(part.get("annotations", [])):
                    if (
                        type(annotation) is not dict
                        or annotation.get("type") != "url_citation"
                    ):
                        continue
                    canonical = _canonical_url(annotation.get("url"))
                    if (
                        canonical is None
                        or canonical[0] in seen
                        or len(results) >= limit
                    ):
                        continue
                    seen.add(canonical[0])
                    title = (
                        _bounded_text(annotation.get("title"), _TITLE_MAX_LENGTH)
                        or canonical[1]
                    )
                    results.append(
                        {
                            "title": title,
                            "url": canonical[0],
                            "content": _citation_content(text, annotation),
                        }
                    )
    return searched, fragments, results


def parse_deepseek_responses_search_response(
    response: object, *, citation_limit: object
) -> dict[str, object]:
    """Strictly normalize documented completed response items and citations."""
    try:
        limit = _validate_citation_limit(citation_limit)
        body = _as_dict(response)
        if body.get("status") != "completed":
            raise DeepSeekResponsesSearchParseError
        output_items = _as_list(body.get("output"))
    except ValueError, TypeError, KeyError:
        raise DeepSeekResponsesSearchParseError from None
    searched, fragments, results = _parse_output_items(output_items, limit)
    if not searched or not fragments:
        raise DeepSeekResponsesSearchParseError
    usage_value = body.get("usage")
    usage: dict[str, int] = {}
    if usage_value is not None:
        usage_obj = _as_dict(usage_value)
        for key in ("input_tokens", "output_tokens", "total_tokens"):
            value = usage_obj.get(key)
            if value is not None:
                if type(value) is not int or value < 0 or value > _USAGE_TOKEN_MAX:
                    raise DeepSeekResponsesSearchParseError
                usage[key] = value
    return {"output": "".join(fragments).strip(), "results": results, "usage": usage}


@dataclass(frozen=True, slots=True)
class DeepSeekSearchResult:
    """Provider-neutral normalized result."""

    output: str
    results: tuple[dict[str, str], ...]
    usage: dict[str, int]

    def as_search_response(self) -> dict[str, object]:
        """Return the shape consumed by the existing search executor."""
        return {"output": self.output, "results": [dict(item) for item in self.results]}


def _decode_response(raw: bytes) -> object:
    return json.loads(
        raw.decode("utf-8"),
        parse_constant=lambda _: (_ for _ in ()).throw(ValueError()),
    )


def _transport_category(error: BaseException) -> DeepSeekSearchErrorCategory:
    if isinstance(error, (asyncio.TimeoutError, TimeoutError, HttpTimeoutError)):
        return DeepSeekSearchErrorCategory.TIMEOUT
    if isinstance(error, UpstreamNetworkError):
        return DeepSeekSearchErrorCategory.TRANSPORT_ERROR
    if isinstance(error, UpstreamConnectionError):
        return DeepSeekSearchErrorCategory.TRANSPORT_ERROR
    return DeepSeekSearchErrorCategory.CONNECTION_ERROR


async def _execute(
    client: DeepSeekResponsesSearchClient, request: DeepSeekResponsesSearchRequest
) -> DeepSeekSearchResult:
    try:
        headers = {
            "Authorization": f"Bearer {client._credential}",
            "Content-Type": "application/json",
        }
        async with AsyncClient(timeout=request.timeout, max_redirects=0) as http_client:
            response = await request_bounded_response(
                http_client,
                "POST",
                f"{request.origin}/responses",
                headers=headers,
                json=request.body,
                max_success_bytes=DEEPSEEK_RESPONSES_SEARCH_RESPONSE_MAX_BYTES,
                max_error_bytes=DEEPSEEK_RESPONSES_SEARCH_RESPONSE_MAX_BYTES,
                allow_redirects=False,
            )
        if not isinstance(response, BoundedHttpResponse):
            raise DeepSeekSearchError(DeepSeekSearchErrorCategory.INVALID_SHAPE)
        if not 200 <= response.status_code < 300:
            raise DeepSeekSearchError(
                DeepSeekSearchErrorCategory.HTTP_ERROR, status_code=response.status_code
            )
        try:
            decoded = _decode_response(response.content)
        except MemoryError:
            raise
        except Exception:
            raise DeepSeekSearchError(
                DeepSeekSearchErrorCategory.INVALID_JSON
            ) from None
        normalized = parse_deepseek_responses_search_response(
            decoded, citation_limit=request.citation_limit
        )
        return DeepSeekSearchResult(
            output=cast(str, normalized["output"]),
            results=tuple(cast(list[dict[str, str]], normalized["results"])),
            usage=cast(dict[str, int], normalized["usage"]),
        )
    except asyncio.CancelledError:
        raise
    except MemoryError:
        raise
    except DeepSeekSearchError:
        raise
    except DeepSeekResponsesSearchParseError:
        raise DeepSeekSearchError(DeepSeekSearchErrorCategory.INVALID_SHAPE) from None
    except UpstreamResponseTooLargeError:
        raise DeepSeekSearchError(DeepSeekSearchErrorCategory.BODY_LIMIT) from None
    except Exception as error:
        raise DeepSeekSearchError(_transport_category(error)) from None


class DeepSeekResponsesSearchClient:
    """Single-attempt client for the official DeepSeek Responses endpoint."""

    def __init__(
        self,
        credential: object = None,
        *,
        api_key: object | None = None,
        origin: object = DEEPSEEK_RESPONSES_OFFICIAL_ORIGIN,
        base_url: object | None = None,
        timeout: object = DEFAULT_DEEPSEEK_RESPONSES_SEARCH_TIMEOUT,
    ) -> None:
        if api_key is not None:
            if credential is not None:
                raise ValueError("DeepSeek Responses credential was supplied twice")
            credential = api_key
        if type(credential) is not str or not credential.strip():
            raise ValueError("DeepSeek Responses credential must be a non-empty string")
        self._credential = credential.strip()
        self._origin = normalize_deepseek_responses_origin(
            base_url if base_url is not None else origin
        )
        self._timeout = _normalize_timeout(timeout)

    async def execute(
        self,
        query: object,
        *,
        model: object = DEEPSEEK_RESPONSES_SEARCH_MODEL,
        max_output_tokens: object = DEFAULT_DEEPSEEK_RESPONSES_SEARCH_MAX_OUTPUT_TOKENS,
        citation_limit: object = DEFAULT_DEEPSEEK_RESPONSES_SEARCH_CITATION_LIMIT,
    ) -> DeepSeekSearchResult:
        """Perform one request and return a normalized result."""
        request = build_deepseek_responses_search_request(
            query=query,
            origin=self._origin,
            model=model,
            max_output_tokens=max_output_tokens,
            citation_limit=citation_limit,
            timeout=self._timeout,
        )
        return await _execute(self, request)

    async def search(
        self,
        query: object,
        *,
        model: object = DEEPSEEK_RESPONSES_SEARCH_MODEL,
        max_output_tokens: object = DEFAULT_DEEPSEEK_RESPONSES_SEARCH_MAX_OUTPUT_TOKENS,
        citation_limit: object = DEFAULT_DEEPSEEK_RESPONSES_SEARCH_CITATION_LIMIT,
    ) -> dict[str, object]:
        """Perform one request and return the provider-neutral search mapping."""
        return (
            await self.execute(
                query,
                model=model,
                max_output_tokens=max_output_tokens,
                citation_limit=citation_limit,
            )
        ).as_search_response()


__all__ = [
    "DEEPSEEK_RESPONSES_OFFICIAL_ORIGIN",
    "DEEPSEEK_RESPONSES_SEARCH_MODEL",
    "DEEPSEEK_RESPONSES_SEARCH_RESPONSE_MAX_BYTES",
    "DEEPSEEK_RESPONSES_SEARCH_TOKEN_LIMITS",
    "DEFAULT_DEEPSEEK_RESPONSES_SEARCH_TIMEOUT",
    "DEFAULT_DEEPSEEK_RESPONSES_SEARCH_MAX_OUTPUT_TOKENS",
    "DEFAULT_DEEPSEEK_RESPONSES_SEARCH_CITATION_LIMIT",
    "DeepSeekResponsesSearchParseError",
    "DeepSeekResponsesSearchRequest",
    "DeepSeekSearchError",
    "DeepSeekSearchErrorCategory",
    "DeepSeekSearchResult",
    "DeepSeekResponsesSearchClient",
    "build_deepseek_responses_search_request",
    "normalize_deepseek_responses_origin",
    "parse_deepseek_responses_search_response",
]
