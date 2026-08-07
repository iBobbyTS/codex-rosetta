"""Pure request and response contracts for DeepSeek hosted web search."""

from __future__ import annotations

import math
from dataclasses import dataclass
from ipaddress import IPv6Address
from typing import Final, Never, cast
from urllib.parse import urlsplit, urlunsplit

from codex_rosetta.observability.redaction import SecretRedactor

DEEPSEEK_RESPONSES_OFFICIAL_ORIGIN = "https://api.deepseek.com"
DEEPSEEK_RESPONSES_SEARCH_MODEL = "deepseek-v4-flash"
DEEPSEEK_RESPONSES_SEARCH_TOKEN_LIMITS = frozenset({512, 1024, 1536})
DEEPSEEK_RESPONSES_SEARCH_RESPONSE_MAX_BYTES = 4 * 1024 * 1024

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


class DeepSeekResponsesSearchParseError(ValueError):
    """A static, provider-neutral failure for an invalid hosted-search response."""

    def __init__(self) -> None:
        super().__init__(_PARSE_ERROR_MESSAGE)


class DeepSeekResponsesSearchCredentialCollisionError(ValueError):
    """A static failure when hosted-search output reconstructs a credential."""

    def __init__(self) -> None:
        super().__init__(_CREDENTIAL_COLLISION_ERROR_MESSAGE)


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
            if detector.feed(output.encode("utf-8")):
                collision = True
            for result in results:
                for field in ("title", "url", "content"):
                    if not collision and detector.feed(result[field].encode("utf-8")):
                        collision = True
        except MemoryError as exc:
            memory_error = exc
        except Exception:
            failed = True
        finally:
            try:
                detector.finish()
            except MemoryError as exc:
                if memory_error is None:
                    memory_error = exc
            except Exception:
                if memory_error is None:
                    failed = True
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

    normalized = parse_deepseek_responses_search_response(
        response,
        citation_limit=citation_limit,
    )
    if _redactor_contains_exact(redactor, normalized):
        raise DeepSeekResponsesSearchCredentialCollisionError
    if _literal_publication_sequence_contains_credential(redactor, normalized):
        raise DeepSeekResponsesSearchCredentialCollisionError
    return normalized


__all__ = [
    "DEEPSEEK_RESPONSES_OFFICIAL_ORIGIN",
    "DEEPSEEK_RESPONSES_SEARCH_MODEL",
    "DEEPSEEK_RESPONSES_SEARCH_RESPONSE_MAX_BYTES",
    "DEEPSEEK_RESPONSES_SEARCH_TOKEN_LIMITS",
    "DeepSeekResponsesSearchCredentialCollisionError",
    "DeepSeekResponsesSearchParseError",
    "DeepSeekResponsesSearchRequest",
    "build_deepseek_responses_search_request",
    "normalize_deepseek_responses_origin",
    "parse_deepseek_responses_search_response",
    "publish_deepseek_responses_search_response",
]
