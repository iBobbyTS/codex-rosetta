"""Pure request contract for DeepSeek Responses hosted web search."""

from __future__ import annotations

import math
from dataclasses import dataclass
from urllib.parse import urlsplit

DEEPSEEK_RESPONSES_OFFICIAL_ORIGIN = "https://api.deepseek.com"
DEEPSEEK_RESPONSES_SEARCH_MODEL = "deepseek-v4-flash"
DEEPSEEK_RESPONSES_SEARCH_TOKEN_LIMITS = frozenset({512, 1024, 1536})

_QUERY_MAX_LENGTH = 4000
_CITATION_LIMIT_RANGE = range(1, 9)
_SEARCH_PROMPT_PREFIX = (
    "Search the web for the following query. Return a concise factual answer and "
    "cite the sources you used.\n\nQuery: "
)


def normalize_deepseek_responses_origin(origin: object) -> str:
    """Validate an official DeepSeek root URL and return its canonical origin."""
    if not isinstance(origin, str) or not origin or origin != origin.strip():
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
    if not isinstance(query, str):
        raise ValueError("DeepSeek Responses search query must be a string")
    normalized = query.strip()
    if not 1 <= len(normalized) <= _QUERY_MAX_LENGTH:
        raise ValueError(
            "DeepSeek Responses search query length must be from 1 to 4000"
        )
    return normalized


def _validate_model(model: object) -> str:
    if not isinstance(model, str) or model != DEEPSEEK_RESPONSES_SEARCH_MODEL:
        raise ValueError("DeepSeek Responses search model is not supported")
    return model


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
    if isinstance(timeout, bool) or not isinstance(timeout, int | float):
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


__all__ = [
    "DEEPSEEK_RESPONSES_OFFICIAL_ORIGIN",
    "DEEPSEEK_RESPONSES_SEARCH_MODEL",
    "DEEPSEEK_RESPONSES_SEARCH_TOKEN_LIMITS",
    "DeepSeekResponsesSearchRequest",
    "build_deepseek_responses_search_request",
    "normalize_deepseek_responses_origin",
]
