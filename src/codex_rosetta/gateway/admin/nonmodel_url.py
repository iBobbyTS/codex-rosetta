"""Provider-specific URL handling for non-model Admin requests."""

from __future__ import annotations

import re
from urllib.parse import urlsplit, urlunsplit


_TERMINAL_VERSION_PATH = re.compile(r"/v[0-9]/?$", re.IGNORECASE)


def strip_terminal_nonmodel_version(base_url: str) -> str:
    """Remove at most one terminal ``/v<digit>`` path from *base_url*.

    The match is case-insensitive and accepts one trailing slash.  Other paths
    and URL components are preserved verbatim, including query and fragment.
    """
    parts = urlsplit(base_url)
    if _TERMINAL_VERSION_PATH.search(parts.path) is None:
        return base_url
    path = _TERMINAL_VERSION_PATH.sub("", parts.path, count=1)
    return urlunsplit((parts.scheme, parts.netloc, path, parts.query, parts.fragment))


__all__ = ["strip_terminal_nonmodel_version"]
