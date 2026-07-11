"""Targeted API-token redaction for persisted gateway diagnostics."""

from __future__ import annotations

import json
import re
from collections.abc import Iterable, Mapping
from copy import deepcopy
from typing import Any

REDACTED = "[REDACTED]"

_BEARER_RE = re.compile(r"(?i)(\bBearer\s+)[A-Za-z0-9._~+/=-]+")


def _normalized_key(value: Any) -> str:
    return re.sub(r"[^a-z0-9]", "", str(value).lower())


def _is_token_key(value: Any) -> bool:
    """Return whether a field explicitly carries an API/auth token."""
    normalized = _normalized_key(value)
    return (
        normalized == "authorization"
        or normalized == "token"
        or normalized.endswith("token")
        or normalized == "apikey"
        or normalized.endswith("apikey")
    )


def _iter_config_values(value: Any, key: Any = "") -> Iterable[tuple[Any, Any]]:
    """Yield nested config values together with their owning field name."""
    yield key, value
    if isinstance(value, Mapping):
        for child_key, child_value in value.items():
            yield from _iter_config_values(child_value, child_key)
    elif isinstance(value, list):
        for item in value:
            yield from _iter_config_values(item, key)


def _add_token(values: set[str], value: Any) -> None:
    """Add a resolved non-empty API token to the redaction set."""
    if isinstance(value, str) and value and "${" not in value:
        values.add(value)


def collect_token_values(config: Mapping[str, Any]) -> set[str]:
    """Collect configured Gateway/provider API tokens for exact-value redaction."""
    values: set[str] = set()
    for key, value in _iter_config_values(config):
        normalized = _normalized_key(key)
        if _is_token_key(key):
            _add_token(values, value)
        if normalized == "apikeys" and isinstance(value, Mapping):
            _add_token(values, value.get("key"))
        elif normalized == "apikeys":
            _add_token(values, value)
    return values


class SecretRedactor:
    """Redact configured API tokens, Bearer values, and token JSON fields."""

    def __init__(self, token_values: Iterable[str] = ()) -> None:
        self.update(token_values)

    def update(self, token_values: Iterable[str]) -> None:
        """Replace the in-memory set of exact API-token values."""
        self._token_values = tuple(
            sorted(
                {
                    value
                    for value in token_values
                    if isinstance(value, str) and value and "${" not in value
                },
                key=len,
                reverse=True,
            )
        )

    def redact(self, value: Any) -> Any:
        """Return a deep redacted copy while preserving non-secret content."""
        return self._redact(deepcopy(value))

    def _redact(self, value: Any, *, token_field: bool = False) -> Any:
        if token_field:
            return REDACTED
        if isinstance(value, str):
            redacted = _BEARER_RE.sub(r"\1[REDACTED]", value)
            for token in self._token_values:
                redacted = redacted.replace(token, REDACTED)
            return redacted
        if isinstance(value, bytes):
            text = value.decode("utf-8", errors="replace")
            return self._redact(text).encode("utf-8")
        if isinstance(value, dict):
            redacted = {
                key: self._redact(
                    item,
                    token_field=_is_token_key(key),
                )
                for key, item in value.items()
            }
            function = redacted.get("function")
            if isinstance(function, dict):
                arguments = function.get("arguments")
                if isinstance(arguments, str):
                    try:
                        parsed_arguments = json.loads(arguments)
                    except json.JSONDecodeError:
                        pass
                    else:
                        redacted_arguments = self._redact(parsed_arguments)
                        if redacted_arguments != parsed_arguments:
                            function["arguments"] = json.dumps(
                                redacted_arguments,
                                ensure_ascii=False,
                            )
            return redacted
        if isinstance(value, list):
            return [self._redact(item) for item in value]
        if isinstance(value, tuple):
            return tuple(self._redact(item) for item in value)
        return value
