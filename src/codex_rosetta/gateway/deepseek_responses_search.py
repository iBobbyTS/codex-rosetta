"""Pure request and response contracts for DeepSeek hosted web search."""

from __future__ import annotations

import asyncio
import json
import math
from dataclasses import dataclass
from enum import StrEnum
from ipaddress import IPv6Address
from typing import Any, Final, Never, cast
from urllib.parse import urlsplit, urlunsplit

from codex_rosetta._vendor.httpclient import AsyncClient
from codex_rosetta.observability.redaction import SecretRedactor

from .transport._base import (
    UpstreamConnectionError,
    UpstreamNetworkError,
    UpstreamResponseTooLargeError,
)
from .transport.http.transport import request_bounded_response

DEEPSEEK_RESPONSES_OFFICIAL_ORIGIN = "https://api.deepseek.com"
DEEPSEEK_RESPONSES_SEARCH_MODEL = "deepseek-v4-flash"
DEEPSEEK_RESPONSES_SEARCH_TOKEN_LIMITS = frozenset({512, 1024, 1536})
DEEPSEEK_RESPONSES_SEARCH_RESPONSE_MAX_BYTES = 4 * 1024 * 1024
DEFAULT_DEEPSEEK_RESPONSES_SEARCH_TIMEOUT = 120.0
DEFAULT_DEEPSEEK_RESPONSES_SEARCH_MAX_OUTPUT_TOKENS = 1024
DEFAULT_DEEPSEEK_RESPONSES_SEARCH_CITATION_LIMIT = 5

_QUERY_MAX_LENGTH = 4000
_CITATION_LIMIT_RANGE = range(1, 9)
_CONTAINER_MAX_ITEMS = 256
_AGGREGATE_VISIT_MAX = 4096
_EXACT_STRING_CHAR_MAX = 1_000_000
_OUTPUT_MAX_LENGTH = 64_000
_RESULT_TITLE_MAX_LENGTH = 500
_RESULT_URL_MAX_LENGTH = 8192
_RESULT_CONTENT_MAX_LENGTH = 1200
_USAGE_TOKEN_MAX = 1_000_000_000
_PARSE_ERROR_MESSAGE: Final = "DeepSeek Responses search response is invalid"
_CREDENTIAL_COLLISION_ERROR_MESSAGE: Final = (
    "DeepSeek Responses search response contains a configured credential; "
    "response blocked"
)
_USAGE_FIELDS: Final = ("input_tokens", "output_tokens", "total_tokens")
_SEARCH_PROMPT_PREFIX = (
    "Search the web for the following query. Return a concise factual answer and "
    "cite the sources you used.\n\nQuery: "
)


def _bounded_status_code(value: object) -> int | None:
    """Keep only ordinary HTTP status integers useful to downstream mapping."""
    if type(value) is int and 100 <= value <= 599:
        return value
    return None


class DeepSeekResponsesSearchParseError(ValueError):
    """A static, provider-neutral failure for an invalid hosted-search response."""

    def __init__(self) -> None:
        super().__init__(_PARSE_ERROR_MESSAGE)


class DeepSeekResponsesSearchCredentialCollisionError(ValueError):
    """A static failure when hosted-search output reconstructs a credential."""

    def __init__(self) -> None:
        super().__init__(_CREDENTIAL_COLLISION_ERROR_MESSAGE)


class DeepSeekSearchErrorCategory(StrEnum):
    """Bounded categories exposed to the later search-chain owner."""

    CONNECTION_ERROR = "connection_error"
    TRANSPORT_ERROR = "transport_error"
    TIMEOUT = "timeout"
    HTTP_ERROR = "http_error"
    INVALID_JSON = "invalid_json"
    INVALID_SHAPE = "invalid_shape"
    BODY_LIMIT = "body_limit"
    RESPONSE_TOO_LARGE = "body_limit"
    CREDENTIAL_COLLISION = "credential_collision"


class DeepSeekSearchError(RuntimeError):
    """A bounded, provider-neutral DeepSeek adapter error."""

    def __init__(
        self,
        category: DeepSeekSearchErrorCategory,
        *,
        status_code: int | None = None,
    ) -> None:
        self.category = category
        self.status_code = _bounded_status_code(status_code)
        super().__init__(category.value)


# Kept as a compatibility spelling for the accepted publication seam.
DeepSeekCredentialCollisionError = DeepSeekResponsesSearchCredentialCollisionError


def normalize_deepseek_responses_origin(origin: object) -> str:
    """Validate an official DeepSeek root URL and return its canonical origin."""
    if type(origin) is not str or not origin or origin != origin.strip():
        raise ValueError("DeepSeek Responses origin must be the official HTTPS root")
    if any(ord(character) < 0x20 for character in origin):
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
        or parsed.hostname is None
        or parsed.hostname.lower() != "api.deepseek.com"
        or parsed.netloc.lower() not in {"api.deepseek.com", "api.deepseek.com:443"}
        or port not in (None, 443)
        or parsed.username is not None
        or parsed.password is not None
        or parsed.path not in ("", "/")
        or parsed.query
        or parsed.fragment
        or "?" in origin
        or "#" in origin
    ):
        raise ValueError("DeepSeek Responses origin must be the official HTTPS root")

    return DEEPSEEK_RESPONSES_OFFICIAL_ORIGIN


def _normalize_query(query: object) -> str:
    if type(query) is not str:
        raise ValueError("DeepSeek Responses search query must be a string")
    normalized = query.strip()
    if not 1 <= len(normalized) <= _QUERY_MAX_LENGTH:
        raise ValueError(
            "DeepSeek Responses search query length must be from 1 to 4000"
        )
    return normalized


def _validate_model(model: object) -> str:
    if type(model) is not str or model != DEEPSEEK_RESPONSES_SEARCH_MODEL:
        raise ValueError("DeepSeek Responses search model is not supported")
    return DEEPSEEK_RESPONSES_SEARCH_MODEL


def _validate_max_output_tokens(max_output_tokens: object) -> int:
    if (
        type(max_output_tokens) is not int
        or max_output_tokens not in DEEPSEEK_RESPONSES_SEARCH_TOKEN_LIMITS
    ):
        raise ValueError("DeepSeek Responses max_output_tokens is not supported")
    return max_output_tokens


def _validate_citation_limit(citation_limit: object) -> int:
    if type(citation_limit) is not int or citation_limit not in _CITATION_LIMIT_RANGE:
        raise ValueError("DeepSeek Responses citation_limit must be from 1 to 8")
    return citation_limit


def _normalize_timeout(timeout: object) -> float:
    if type(timeout) is not int and type(timeout) is not float:
        raise ValueError("DeepSeek Responses timeout must be a finite positive number")
    try:
        normalized = float(timeout)
    except OverflowError, ValueError:
        raise ValueError(
            "DeepSeek Responses timeout must be a finite positive number"
        ) from None
    if not math.isfinite(normalized) or normalized <= 0:
        raise ValueError("DeepSeek Responses timeout must be a finite positive number")
    return normalized


@dataclass(frozen=True, slots=True)
class DeepSeekResponsesSearchRequest:
    """A validated, inert DeepSeek hosted-search request value."""

    origin: str
    model: str
    query: str
    max_output_tokens: int
    citation_limit: int
    timeout: float

    def __post_init__(self) -> None:
        """Keep direct construction on the same validation boundary as the builder."""
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
        """Return a fresh exact five-field Responses API request body."""
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
    """Validate local controls and construct an inert hosted-search request."""
    return DeepSeekResponsesSearchRequest(
        origin=normalize_deepseek_responses_origin(origin),
        model=_validate_model(model),
        query=_normalize_query(query),
        max_output_tokens=_validate_max_output_tokens(max_output_tokens),
        citation_limit=_validate_citation_limit(citation_limit),
        timeout=_normalize_timeout(timeout),
    )


def _raise_parse_error() -> Never:
    raise DeepSeekResponsesSearchParseError


@dataclass(slots=True)
class _ParseBudget:
    visits: int = 0
    exact_string_chars: int = 0

    def consume_visits(self, count: int) -> None:
        self.visits += count
        if self.visits > _AGGREGATE_VISIT_MAX:
            _raise_parse_error()

    def consume_exact_string(self, value: object) -> str:
        if type(value) is not str:
            _raise_parse_error()
        self.exact_string_chars += len(value)
        if self.exact_string_chars > _EXACT_STRING_CHAR_MAX:
            _raise_parse_error()
        return value


def _bounded_exact_dict(value: object, budget: _ParseBudget) -> dict[object, object]:
    if type(value) is not dict:
        _raise_parse_error()
    value = cast(dict[object, object], value)
    if len(value) > _CONTAINER_MAX_ITEMS:
        _raise_parse_error()
    for key in value:
        budget.consume_exact_string(key)
    return value


def _bounded_exact_list(value: object, budget: _ParseBudget) -> list[object]:
    if type(value) is not list:
        _raise_parse_error()
    value = cast(list[object], value)
    if len(value) > _CONTAINER_MAX_ITEMS:
        _raise_parse_error()
    budget.consume_visits(len(value))
    return value


def _typed_item(
    value: object, budget: _ParseBudget
) -> tuple[str, dict[object, object]] | None:
    value_type = type(value)
    if value_type is not dict:
        if issubclass(value_type, dict):
            _raise_parse_error()
        return None
    item = _bounded_exact_dict(value, budget)
    item_type = budget.consume_exact_string(item.get("type"))
    return item_type, item


def _valid_citation_hostname(hostname: str) -> bool:
    if ":" in hostname:
        try:
            IPv6Address(hostname)
        except ValueError:
            return False
        return True
    labels = hostname[:-1].split(".") if hostname.endswith(".") else hostname.split(".")
    return bool(labels) and all(
        label
        and not label.startswith("-")
        and not label.endswith("-")
        and all(
            "a" <= character.lower() <= "z"
            or "0" <= character <= "9"
            or character == "-"
            for character in label
        )
        for label in labels
    )


def _canonicalize_citation_url(
    value: object, budget: _ParseBudget
) -> tuple[str, str] | None:
    value = budget.consume_exact_string(value)
    if not value or any(
        character.isspace() or ord(character) < 0x20 or ord(character) == 0x7F
        for character in value
    ):
        return None
    try:
        parsed = urlsplit(value)
        if not parsed.netloc.isascii():
            return None
        port = parsed.port
        hostname = parsed.hostname
    except ValueError:
        return None
    if (
        parsed.scheme.lower() not in {"http", "https"}
        or hostname is None
        or not hostname
        or not _valid_citation_hostname(hostname)
        or parsed.username is not None
        or parsed.password is not None
        or any(
            character.isspace()
            or ord(character) < 0x20
            or character in {"/", "\\", "@", "?", "#"}
            for character in hostname
        )
    ):
        return None

    scheme = parsed.scheme.lower()
    canonical_hostname = hostname.lower()
    rendered_hostname = (
        f"[{canonical_hostname}]" if ":" in canonical_hostname else canonical_hostname
    )
    default_port = (scheme == "http" and port == 80) or (
        scheme == "https" and port == 443
    )
    netloc = (
        rendered_hostname
        if port is None or default_port
        else f"{rendered_hostname}:{port}"
    )
    path = parsed.path or "/"
    canonical_length = (
        len(scheme)
        + 3
        + len(netloc)
        + len(path)
        + (1 + len(parsed.query) if parsed.query else 0)
    )
    if canonical_length > _RESULT_URL_MAX_LENGTH:
        return None
    canonical = urlunsplit((scheme, netloc, path, parsed.query, ""))
    return canonical, canonical_hostname


def _citation_content(annotation: dict[object, object], text: str) -> str:
    start = annotation.get("start_index")
    end = annotation.get("end_index")
    if (
        type(start) is not int
        or type(end) is not int
        or start < 0
        or end < start
        or end > len(text)
    ):
        return ""
    return text[start : min(end, start + _RESULT_CONTENT_MAX_LENGTH)]


def _trimmed_prefix(value: str, limit: int) -> str:
    start = 0
    end = len(value)
    while start < end and value[start].isspace():
        start += 1
    while end > start and value[end - 1].isspace():
        end -= 1
    return value[start : min(end, start + limit)]


def _validated_citation_title(
    annotation: dict[object, object], budget: _ParseBudget
) -> str | None:
    title = annotation.get("title")
    if title is None:
        return None
    title = budget.consume_exact_string(title)
    return _trimmed_prefix(title, _RESULT_TITLE_MAX_LENGTH)


def _citation_title(title: str | None, hostname: str) -> str:
    normalized = title or hostname
    return normalized[:_RESULT_TITLE_MAX_LENGTH]


def _parse_citations(
    annotations_value: object,
    *,
    budget: _ParseBudget,
    text: str,
    citation_limit: int,
    seen_urls: set[str],
    results: list[dict[str, str]],
) -> None:
    annotations = _bounded_exact_list(annotations_value, budget)
    for value in annotations:
        typed = _typed_item(value, budget)
        if typed is None:
            continue
        annotation_type, annotation = typed
        if annotation_type != "url_citation":
            continue
        title_value = _validated_citation_title(annotation, budget)
        canonicalized = _canonicalize_citation_url(annotation.get("url"), budget)
        if canonicalized is None:
            continue
        url, hostname = canonicalized
        title = _citation_title(title_value, hostname)
        content = _citation_content(annotation, text)
        if url in seen_urls or len(results) >= citation_limit:
            continue
        seen_urls.add(url)
        results.append(
            {
                "title": title,
                "url": url,
                "content": content,
            }
        )


def _parse_usage(
    response: dict[object, object], budget: _ParseBudget
) -> dict[str, int]:
    if "usage" not in response:
        return {}
    usage = _bounded_exact_dict(response["usage"], budget)
    normalized: dict[str, int] = {}
    for field in _USAGE_FIELDS:
        if field not in usage:
            continue
        value = usage[field]
        if type(value) is not int or not 0 <= value <= _USAGE_TOKEN_MAX:
            _raise_parse_error()
        normalized[field] = value
    return normalized


def _bounded_joined_output(text_fragments: list[str]) -> str:
    first_item = -1
    first_offset = 0
    for item_index, text in enumerate(text_fragments):
        offset = 0
        while offset < len(text) and text[offset].isspace():
            offset += 1
        if offset < len(text):
            first_item = item_index
            first_offset = offset
            break
    if first_item < 0:
        _raise_parse_error()

    last_item = -1
    last_offset = 0
    for item_index in range(len(text_fragments) - 1, first_item - 1, -1):
        text = text_fragments[item_index]
        offset = len(text)
        while offset > 0 and text[offset - 1].isspace():
            offset -= 1
        if offset > 0:
            last_item = item_index
            last_offset = offset
            break

    if first_item == last_item:
        final_length = last_offset - first_offset
    else:
        final_length = len(text_fragments[first_item]) - first_offset
        final_length += sum(
            len(text_fragments[index]) for index in range(first_item + 1, last_item)
        )
        final_length += last_offset
    if not 1 <= final_length <= _OUTPUT_MAX_LENGTH:
        _raise_parse_error()

    if first_item == last_item:
        return text_fragments[first_item][first_offset:last_offset]
    pieces = [text_fragments[first_item][first_offset:]]
    pieces.extend(text_fragments[first_item + 1 : last_item])
    pieces.append(text_fragments[last_item][:last_offset])
    return "".join(pieces)


def parse_deepseek_responses_search_response(
    response: object,
    *,
    citation_limit: object,
) -> dict[str, object]:
    """Parse one completed hosted-search response into a bounded neutral value.

    The parser consumes only already-decoded Python/JSON values. It performs no
    transport, credential, storage, logging, or filesystem work.
    """
    try:
        validated_limit = _validate_citation_limit(citation_limit)
    except ValueError:
        raise DeepSeekResponsesSearchParseError from None

    budget = _ParseBudget()
    body = _bounded_exact_dict(response, budget)
    status = budget.consume_exact_string(body.get("status"))
    if status != "completed":
        _raise_parse_error()
    output_items = _bounded_exact_list(body.get("output"), budget)

    completed_search = False
    text_fragments: list[str] = []
    results: list[dict[str, str]] = []
    seen_urls: set[str] = set()

    for value in output_items:
        typed = _typed_item(value, budget)
        if typed is None:
            continue
        item_type, item = typed
        if item_type == "reasoning":
            continue
        if item_type == "web_search_call":
            search_status = budget.consume_exact_string(item.get("status"))
            completed_search = completed_search or search_status == "completed"
            continue
        if item_type != "message":
            continue

        content_items = _bounded_exact_list(item.get("content"), budget)
        for content_value in content_items:
            content_typed = _typed_item(content_value, budget)
            if content_typed is None:
                continue
            content_type, content = content_typed
            if content_type != "output_text":
                continue
            text = budget.consume_exact_string(content.get("text"))
            if not text:
                _raise_parse_error()
            text_fragments.append(text)
            _parse_citations(
                content.get("annotations"),
                budget=budget,
                text=text,
                citation_limit=validated_limit,
                seen_urls=seen_urls,
                results=results,
            )

    if not completed_search:
        _raise_parse_error()
    output = _bounded_joined_output(text_fragments)

    return {
        "output": output,
        "results": results,
        "usage": _parse_usage(body, budget),
    }


def _redactor_contains_json_semantic(
    redactor: SecretRedactor, raw_response: bytes
) -> bool:
    failed = False
    collision = False
    try:
        collision = SecretRedactor.contains_json_semantic(redactor, raw_response)
    except MemoryError:
        raise
    except Exception:
        failed = True
    if failed:
        _raise_parse_error()
    return collision


def _redactor_contains_exact(
    redactor: SecretRedactor, normalized: dict[str, object]
) -> bool:
    failed = False
    collision = False
    try:
        collision = SecretRedactor.contains_exact(redactor, normalized)
    except MemoryError:
        raise
    except Exception:
        failed = True
    if failed:
        _raise_parse_error()
    return collision


def _finish_literal_detector(
    detector: Any, memory_error: MemoryError | None
) -> tuple[MemoryError | None, bool]:
    try:
        detector.finish()
    except MemoryError as exc:
        return memory_error or exc, False
    except Exception:
        return memory_error, memory_error is None
    return memory_error, False


def _encode_literal_detector_fragment(value: str) -> bytes:
    """Encode a parser-bounded text fragment without rejecting lone surrogates."""
    return value.encode("utf-8", errors="surrogatepass")


def _literal_publication_sequence_contains_credential(
    redactor: SecretRedactor, normalized: dict[str, object]
) -> bool:
    output = cast(str, normalized["output"])
    results = cast(list[dict[str, str]], normalized["results"])
    collision = False
    failed = False
    memory_error: MemoryError | None = None
    try:
        detector = SecretRedactor.streaming_value_detector(redactor)
    except MemoryError as exc:
        memory_error = exc
    except Exception:
        failed = True
    else:
        try:
            if detector.feed(_encode_literal_detector_fragment(output)):
                collision = True
            for result in results:
                for field in ("title", "url", "content"):
                    if not collision and detector.feed(
                        _encode_literal_detector_fragment(result[field])
                    ):
                        collision = True
        except MemoryError as exc:
            memory_error = exc
        except Exception:
            failed = True
        finally:
            memory_error, finish_failed = _finish_literal_detector(
                detector, memory_error
            )
            failed = failed or finish_failed
    if memory_error is not None:
        raise memory_error
    if failed:
        _raise_parse_error()
    return collision


def publish_deepseek_responses_search_response(
    *,
    raw_response: object,
    response: object,
    citation_limit: object,
    redactor: object,
) -> dict[str, object]:
    """Publish a parsed response only after raw and normalized secret gates."""
    if type(redactor) is not SecretRedactor:
        _raise_parse_error()
    if type(raw_response) is not bytes:
        _raise_parse_error()
    if len(raw_response) > DEEPSEEK_RESPONSES_SEARCH_RESPONSE_MAX_BYTES:
        _raise_parse_error()

    if _redactor_contains_json_semantic(redactor, raw_response):
        raise DeepSeekResponsesSearchCredentialCollisionError

    return _publish_after_raw_gate(
        response=response,
        citation_limit=citation_limit,
        redactor=redactor,
    )


def _publish_after_raw_gate(
    *,
    response: object,
    citation_limit: object,
    redactor: SecretRedactor,
) -> dict[str, object]:
    """Compose the accepted parser and final gate after one raw scan."""
    normalized = parse_deepseek_responses_search_response(
        response,
        citation_limit=citation_limit,
    )
    if _redactor_contains_exact(redactor, normalized):
        raise DeepSeekResponsesSearchCredentialCollisionError
    if _literal_publication_sequence_contains_credential(redactor, normalized):
        raise DeepSeekResponsesSearchCredentialCollisionError
    return normalized


@dataclass(frozen=True, slots=True)
class DeepSeekSearchResult:
    """Provider-neutral result returned by the explicit adapter seam."""

    output: str
    results: tuple[dict[str, str], ...]
    usage: dict[str, int]

    def as_search_response(self) -> dict[str, object]:
        """Return a fresh result mapping without provider-specific state."""
        return {
            "output": self.output,
            "results": [dict(result) for result in self.results],
        }


@dataclass(frozen=True, slots=True)
class _AdapterFailure:
    """Exception-free transfer object crossing the sensitive operation boundary."""

    category: DeepSeekSearchErrorCategory
    status_code: int | None = None


def _reject_non_finite_json_constant(value: str) -> Never:
    del value
    raise ValueError


def _parse_finite_json_float(value: str) -> float:
    parsed = float(value)
    if not math.isfinite(parsed):
        raise ValueError
    return parsed


def _decode_deepseek_response(raw_response: bytes) -> object:
    """Decode one bounded body with strict UTF-8 and standard JSON numbers."""
    return json.loads(
        raw_response.decode("utf-8"),
        parse_constant=_reject_non_finite_json_constant,
        parse_float=_parse_finite_json_float,
    )


def _classify_transport_failure(error: BaseException) -> DeepSeekSearchErrorCategory:
    """Map transport exceptions without inspecting or retaining their text."""
    if isinstance(error, (asyncio.TimeoutError, TimeoutError)):
        return DeepSeekSearchErrorCategory.TIMEOUT
    if isinstance(error, UpstreamNetworkError):
        return (
            DeepSeekSearchErrorCategory.TIMEOUT
            if "timeout" in type(error).__name__.lower()
            else DeepSeekSearchErrorCategory.TRANSPORT_ERROR
        )
    if isinstance(error, UpstreamConnectionError):
        return DeepSeekSearchErrorCategory.TRANSPORT_ERROR
    return DeepSeekSearchErrorCategory.CONNECTION_ERROR


def _raise_adapter_failure(failure: _AdapterFailure) -> Never:
    """Raise a fresh public error after sensitive operation locals are gone."""
    if failure.category is DeepSeekSearchErrorCategory.CREDENTIAL_COLLISION:
        raise DeepSeekResponsesSearchCredentialCollisionError from None
    raise DeepSeekSearchError(
        failure.category,
        status_code=failure.status_code,
    ) from None


async def _execute_deepseek_request(
    *,
    credential: str,
    request: DeepSeekResponsesSearchRequest,
    redactor: SecretRedactor,
) -> DeepSeekSearchResult | _AdapterFailure:
    """Run one bounded request and return only safe values or a failure token."""
    raw_response: bytes | None = None
    decoded_response: object | None = None
    try:
        headers = {
            "Authorization": f"Bearer {credential}",
            "Content-Type": "application/json",
        }
        async with AsyncClient(
            timeout=request.timeout,
            max_redirects=0,
        ) as client:
            response = await request_bounded_response(
                client,
                "POST",
                f"{request.origin}/responses",
                headers=headers,
                json=request.body,
                max_success_bytes=DEEPSEEK_RESPONSES_SEARCH_RESPONSE_MAX_BYTES,
                max_error_bytes=DEEPSEEK_RESPONSES_SEARCH_RESPONSE_MAX_BYTES,
                allow_redirects=False,
            )

        raw_response = response.content
        if type(raw_response) is not bytes:
            return _AdapterFailure(DeepSeekSearchErrorCategory.INVALID_SHAPE)
        if len(raw_response) > DEEPSEEK_RESPONSES_SEARCH_RESPONSE_MAX_BYTES:
            return _AdapterFailure(DeepSeekSearchErrorCategory.BODY_LIMIT)

        status_code = _bounded_status_code(response.status_code)
        # The raw publication gate intentionally precedes status/JSON reporting.
        if _redactor_contains_json_semantic(redactor, raw_response):
            return _AdapterFailure(DeepSeekSearchErrorCategory.CREDENTIAL_COLLISION)
        if status_code is None:
            return _AdapterFailure(DeepSeekSearchErrorCategory.INVALID_SHAPE)
        if not 200 <= status_code < 300:
            return _AdapterFailure(
                DeepSeekSearchErrorCategory.HTTP_ERROR,
                status_code=status_code,
            )

        try:
            decoded_response = _decode_deepseek_response(raw_response)
        except MemoryError:
            raise
        except Exception:
            return _AdapterFailure(DeepSeekSearchErrorCategory.INVALID_JSON)
        normalized = _publish_after_raw_gate(
            response=decoded_response,
            citation_limit=request.citation_limit,
            redactor=redactor,
        )
        return _normalize_adapter_result(normalized)
    except asyncio.CancelledError:
        raise
    except MemoryError:
        raise
    except DeepSeekResponsesSearchCredentialCollisionError:
        return _AdapterFailure(DeepSeekSearchErrorCategory.CREDENTIAL_COLLISION)
    except DeepSeekResponsesSearchParseError:
        return _AdapterFailure(DeepSeekSearchErrorCategory.INVALID_SHAPE)
    except UpstreamResponseTooLargeError:
        return _AdapterFailure(DeepSeekSearchErrorCategory.BODY_LIMIT)
    except Exception as error:
        return _AdapterFailure(_classify_transport_failure(error))
    finally:
        # Do not leave large/sensitive values in this frame if a debugger keeps it.
        raw_response = None
        decoded_response = None
        credential = ""
        redactor = cast(SecretRedactor, None)
        request = cast(DeepSeekResponsesSearchRequest, None)
        response = None
        headers = None
        client = None


def _normalize_adapter_result(
    normalized: dict[str, object],
) -> DeepSeekSearchResult | _AdapterFailure:
    """Copy the accepted publication value into the explicit result type."""
    output = normalized["output"]
    results_value = normalized["results"]
    usage_value = normalized["usage"]
    if (
        type(output) is not str
        or type(results_value) is not list
        or type(usage_value) is not dict
    ):
        return _AdapterFailure(DeepSeekSearchErrorCategory.INVALID_SHAPE)
    results: list[dict[str, str]] = []
    for result in results_value:
        if type(result) is not dict or any(
            type(result.get(field)) is not str for field in ("title", "url", "content")
        ):
            return _AdapterFailure(DeepSeekSearchErrorCategory.INVALID_SHAPE)
        result = cast(dict[str, object], result)
        results.append(
            {
                "title": cast(str, result["title"]),
                "url": cast(str, result["url"]),
                "content": cast(str, result["content"]),
            }
        )
    usage = {
        key: value
        for key, value in usage_value.items()
        if type(key) is str and type(value) is int
    }
    return DeepSeekSearchResult(
        output=output,
        results=tuple(results),
        usage=usage,
    )


class DeepSeekResponsesSearchClient:
    """Explicit, single-attempt client for official DeepSeek Responses search."""

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
        if base_url is not None:
            origin = base_url
        self._credential = credential
        self._origin = normalize_deepseek_responses_origin(origin)
        self._timeout = _normalize_timeout(timeout)
        self._redactor = SecretRedactor((credential,))

    async def execute(
        self,
        query: object,
        *,
        model: object = DEEPSEEK_RESPONSES_SEARCH_MODEL,
        max_output_tokens: object = DEFAULT_DEEPSEEK_RESPONSES_SEARCH_MAX_OUTPUT_TOKENS,
        citation_limit: object = DEFAULT_DEEPSEEK_RESPONSES_SEARCH_CITATION_LIMIT,
    ) -> DeepSeekSearchResult:
        """Perform at most one request and return a normalized result."""
        # Constructing the request is deliberately before client/transport creation.
        request = build_deepseek_responses_search_request(
            query=query,
            origin=self._origin,
            model=model,
            max_output_tokens=max_output_tokens,
            citation_limit=citation_limit,
            timeout=self._timeout,
        )
        outcome = await _execute_deepseek_request(
            credential=self._credential,
            request=request,
            redactor=self._redactor,
        )
        if isinstance(outcome, _AdapterFailure):
            _raise_adapter_failure(outcome)
        return outcome

    async def search(
        self,
        query: object,
        *,
        model: object = DEEPSEEK_RESPONSES_SEARCH_MODEL,
        max_output_tokens: object = DEFAULT_DEEPSEEK_RESPONSES_SEARCH_MAX_OUTPUT_TOKENS,
        citation_limit: object = DEFAULT_DEEPSEEK_RESPONSES_SEARCH_CITATION_LIMIT,
    ) -> dict[str, object]:
        """Perform one request and return the provider-neutral search mapping."""
        result = await self.execute(
            query,
            model=model,
            max_output_tokens=max_output_tokens,
            citation_limit=citation_limit,
        )
        return result.as_search_response()


__all__ = [
    "DEEPSEEK_RESPONSES_OFFICIAL_ORIGIN",
    "DEEPSEEK_RESPONSES_SEARCH_MODEL",
    "DEEPSEEK_RESPONSES_SEARCH_RESPONSE_MAX_BYTES",
    "DEEPSEEK_RESPONSES_SEARCH_TOKEN_LIMITS",
    "DEFAULT_DEEPSEEK_RESPONSES_SEARCH_TIMEOUT",
    "DEFAULT_DEEPSEEK_RESPONSES_SEARCH_MAX_OUTPUT_TOKENS",
    "DEFAULT_DEEPSEEK_RESPONSES_SEARCH_CITATION_LIMIT",
    "DeepSeekCredentialCollisionError",
    "DeepSeekResponsesSearchCredentialCollisionError",
    "DeepSeekResponsesSearchParseError",
    "DeepSeekResponsesSearchRequest",
    "DeepSeekSearchError",
    "DeepSeekSearchErrorCategory",
    "DeepSeekSearchResult",
    "DeepSeekResponsesSearchClient",
    "build_deepseek_responses_search_request",
    "normalize_deepseek_responses_origin",
    "parse_deepseek_responses_search_response",
    "publish_deepseek_responses_search_response",
]
