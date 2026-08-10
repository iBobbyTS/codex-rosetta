"""Pure, import-inert validation for the official DeepSeek API origin."""

from urllib.parse import urlsplit


DEEPSEEK_OFFICIAL_ORIGIN = "https://api.deepseek.com"
"""Canonical origin accepted by the DeepSeek hosted API."""

# Keep the adapter spelling available to callers while this standalone seam is
# adopted by later sections.  The values are immutable strings.
DEEPSEEK_RESPONSES_OFFICIAL_ORIGIN = DEEPSEEK_OFFICIAL_ORIGIN

_ORIGIN_ERROR = "DeepSeek origin must be the official HTTPS root"
_ALLOWED_NETLOC = frozenset({"api.deepseek.com", "api.deepseek.com:443"})


def normalize_deepseek_origin(origin: object) -> str:
    """Validate and canonicalize an official DeepSeek root URL.

    Only an exact built-in string is accepted.  The scheme and hostname are
    case-insensitive; an optional port of ``443`` and an optional root slash
    are normalized to :data:`DEEPSEEK_OFFICIAL_ORIGIN`.  Userinfo, non-default
    ports, paths, queries, fragments, whitespace, and control characters are
    rejected with a bounded error that never includes the input.

    Args:
        origin: Candidate URL supplied by a caller.

    Returns:
        The canonical official origin.

    Raises:
        ValueError: If ``origin`` is not an accepted official root URL.
    """
    if type(origin) is not str or not origin or origin != origin.strip():
        raise ValueError(_ORIGIN_ERROR)
    if any(ord(character) < 0x20 or ord(character) == 0x7F for character in origin):
        raise ValueError(_ORIGIN_ERROR)
    try:
        parsed = urlsplit(origin)
        port = parsed.port
    except ValueError:
        raise ValueError(_ORIGIN_ERROR) from None
    if (
        parsed.scheme.lower() != "https"
        or (parsed.hostname or "").lower() != "api.deepseek.com"
        or parsed.netloc.lower() not in _ALLOWED_NETLOC
        or port not in (None, 443)
        or parsed.username is not None
        or parsed.password is not None
        or parsed.path not in ("", "/")
        or parsed.query
        or parsed.fragment
    ):
        raise ValueError(_ORIGIN_ERROR)
    return DEEPSEEK_OFFICIAL_ORIGIN


# Explicit descriptive aliases for downstream qualification code.  They are
# aliases, rather than wrappers, so no second validation implementation exists.
normalize_deepseek_responses_origin = normalize_deepseek_origin
normalize_deepseek_search_origin = normalize_deepseek_origin


__all__ = [
    "DEEPSEEK_OFFICIAL_ORIGIN",
    "DEEPSEEK_RESPONSES_OFFICIAL_ORIGIN",
    "normalize_deepseek_origin",
    "normalize_deepseek_responses_origin",
    "normalize_deepseek_search_origin",
]
