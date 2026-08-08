"""Pure, import-inert validation for the official DeepSeek API origin.

This module is deliberately kept outside :mod:`codex_rosetta`.  Consumers that
need to qualify the hosted search provider can import this value seam without
loading the adapter, HTTP transport, configuration, or any other runtime
surface.
"""

from urllib.parse import urlsplit


DEEPSEEK_OFFICIAL_ORIGIN = "https://api.deepseek.com"
"""Canonical origin accepted by the DeepSeek hosted API."""

# Keep the adapter spelling available to callers while this standalone seam is
# adopted by later sections.  The values are immutable strings.
DEEPSEEK_RESPONSES_OFFICIAL_ORIGIN = DEEPSEEK_OFFICIAL_ORIGIN

_ORIGIN_ERROR = "DeepSeek origin must be the official HTTPS root"
_ALLOWED_NETLOC = frozenset({"api.deepseek.com", "api.deepseek.com:443"})


def _parse_origin(origin: str):
    """Return URL components, swallowing parser errors before validation."""
    try:
        parsed = urlsplit(origin)
        return (
            parsed,
            parsed.port,
            parsed.hostname,
            parsed.username,
            parsed.password,
        )
    except ValueError:
        # Keep malformed-authority parser details out of the public exception
        # context; callers receive only the static contract error.
        return None


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
    if type(origin) is not str:
        # Remove the caller-controlled object before constructing the traceback.
        del origin
        raise ValueError(_ORIGIN_ERROR) from None

    if not origin or origin != origin.strip():
        del origin
        raise ValueError(_ORIGIN_ERROR) from None

    if any(ord(character) < 0x20 or ord(character) == 0x7F for character in origin):
        del origin
        raise ValueError(_ORIGIN_ERROR) from None

    parts = _parse_origin(origin)
    if parts is None:
        del origin
        raise ValueError(_ORIGIN_ERROR) from None
    parsed, port, hostname, username, password = parts
    del parts

    valid = (
        parsed.scheme.lower() == "https"
        and hostname is not None
        and hostname.lower() == "api.deepseek.com"
        and parsed.netloc.lower() in _ALLOWED_NETLOC
        and port in (None, 443)
        and username is None
        and password is None
        and parsed.path in ("", "/")
        and not parsed.query
        and not parsed.fragment
        and "?" not in origin
        and "#" not in origin
    )
    if not valid:
        # ParseResult retains the URL, so all value-bearing locals are removed
        # before the exception reaches the caller.
        del origin, parsed, port, hostname, username, password, valid
        raise ValueError(_ORIGIN_ERROR) from None

    del origin, parsed, port, hostname, username, password, valid
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
