"""Offline provider qualification for the explicit DeepSeek search smoke CLI.

The module is intentionally an inert boundary.  It consumes only the accepted
stdlib origin validator and an injected configuration loader; no gateway,
client, transport, filesystem, or runtime code is imported or executed.
"""

from __future__ import annotations

import importlib.util
from collections.abc import Callable
from pathlib import Path
from types import ModuleType
from typing import Final


def _load_origin_contract() -> ModuleType:
    """Load the adjacent pure origin module without importing the application."""
    path = Path(__file__).with_name("deepseek_search_origin.py")
    spec = importlib.util.spec_from_file_location("deepseek_search_origin", path)
    if spec is None or spec.loader is None:
        raise ImportError("DeepSeek origin contract is unavailable") from None
    origin_module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(origin_module)
    return origin_module


_ORIGIN_CONTRACT = _load_origin_contract()
_normalize_origin = _ORIGIN_CONTRACT.normalize_deepseek_origin
_OFFICIAL_ORIGIN = _ORIGIN_CONTRACT.DEEPSEEK_OFFICIAL_ORIGIN

SMOKE_PROVIDER_ID: Final = "deepseek"
SMOKE_QUERY: Final = "latest python release version"
SMOKE_MODES: Final = ("direct",)
SMOKE_MAX_UPSTREAM_CALLS: Final = 1

_QUALIFICATION_ERROR: Final = "DeepSeek search smoke qualification failed"
_ADMISSION_ERROR: Final = "DeepSeek search smoke call admission denied"
_MISSING: Final = object()


class DeepSeekSmokeQualificationError(ValueError):
    """Static, bounded failure for invalid smoke provider qualification."""

    def __init__(self) -> None:
        super().__init__(_QUALIFICATION_ERROR)

    def __repr__(self) -> str:
        return f"{type(self).__name__}()"


class DeepSeekSmokeCallAdmissionError(ValueError):
    """Static, bounded failure for invalid or spent call admission."""

    def __init__(self) -> None:
        super().__init__(_ADMISSION_ERROR)

    def __repr__(self) -> str:
        return f"{type(self).__name__}()"


class QualifiedDeepSeekProvider:
    """Opaque in-memory provider qualification passed to a later composition.

    Only the explicit ``credential`` property exposes the secret to the later
    composition section.  Display, comparison, hashing, and error paths are
    independent of the credential and retain no config row or query.
    """

    __slots__ = ("_credential",)

    def __init__(self, credential: object) -> None:
        if type(credential) is not str or not credential:
            del credential
            raise DeepSeekSmokeQualificationError() from None
        self._credential = credential

    @property
    def credential(self) -> str:
        """Return the selected credential for the later isolated stage."""
        return self._credential

    @property
    def provider_id(self) -> str:
        """Return the fixed built-in provider identity."""
        return SMOKE_PROVIDER_ID

    @property
    def origin(self) -> str:
        """Return the canonical official origin."""
        return _OFFICIAL_ORIGIN

    def __repr__(self) -> str:
        return "<QualifiedDeepSeekProvider>"

    __str__ = __repr__

    def __eq__(self, other: object) -> bool:
        return self is other

    __hash__ = object.__hash__


class CallAdmission:
    """Process-local admission primitive allowing exactly one reservation."""

    __slots__ = ("_reserved",)

    def __init__(self, max_upstream_calls: object) -> None:
        if (
            type(max_upstream_calls) is not int
            or max_upstream_calls != SMOKE_MAX_UPSTREAM_CALLS
        ):
            del max_upstream_calls
            raise DeepSeekSmokeCallAdmissionError() from None
        self._reserved = False

    def reserve(self) -> None:
        """Consume the sole reservation, failing statically when already spent."""
        if self._reserved:
            raise DeepSeekSmokeCallAdmissionError() from None
        self._reserved = True


def _controls_are_literal(
    provider_id: object,
    query: object,
    modes: object,
    max_upstream_calls: object,
) -> bool:
    """Validate fixed controls using exact builtin types before loader access."""
    if type(provider_id) is not str or provider_id != SMOKE_PROVIDER_ID:
        return False
    if type(query) is not str or query != SMOKE_QUERY:
        return False
    if type(modes) is not list or len(modes) != 1:
        return False
    if type(modes[0]) is not str or modes[0] != SMOKE_MODES[0]:
        return False
    return (
        type(max_upstream_calls) is int
        and max_upstream_calls == SMOKE_MAX_UPSTREAM_CALLS
    )


def _credential_from_row(row: dict[object, object]) -> str | None:
    """Resolve one literal, non-empty credential from one provider row."""
    raw = dict.get(row, "api_key", _MISSING)
    if type(raw) is not str:
        return None
    values = tuple(piece.strip() for piece in raw.split(",") if piece.strip())
    if len(values) != 1:
        return None
    credential = values[0]
    if (
        type(credential) is not str
        or not credential
        or "${" in credential
        or "{{" in credential
    ):
        return None
    return credential


def _select_official_provider(config_loader: Callable[[], object]) -> str | None:
    """Load and qualify exactly one enabled official DeepSeek provider row.

    Only ordinary ``Exception`` is collapsed.  ``BaseException`` control and
    resource signals intentionally escape unchanged for the later composition.
    """
    try:
        config = config_loader()
        if type(config) is not dict:
            return None
        providers = dict.get(config, "providers", _MISSING)
        if type(providers) is not dict:
            return None

        selected: str | None = None
        for name, row in dict.items(providers):
            if type(name) is not str or type(row) is not dict:
                return None
            enabled = dict.get(row, "enabled", True)
            if type(enabled) is not bool:
                return None
            if not enabled:
                continue
            provider = dict.get(row, "provider", _MISSING)
            if type(provider) is not str:
                return None
            if provider != SMOKE_PROVIDER_ID:
                continue
            origin = dict.get(row, "base_url", _MISSING)
            if type(origin) is not str:
                return None
            try:
                _normalize_origin(origin)
            except Exception as error:
                if isinstance(error, MemoryError):
                    raise
                return None
            credential = _credential_from_row(row)
            if credential is None or selected is not None:
                return None
            selected = credential
        return selected
    except Exception as error:
        if isinstance(error, MemoryError):
            raise
        return None


def qualify_deepseek_provider(
    *,
    provider_id: object,
    query: object,
    modes: object,
    max_upstream_calls: object,
    config_loader: Callable[[], object],
) -> QualifiedDeepSeekProvider:
    """Validate fixed smoke controls and select one official provider.

    The loader is injected for offline tests and is called only after literal
    controls pass.  No loader or config object is retained in the result.
    """
    if not _controls_are_literal(provider_id, query, modes, max_upstream_calls):
        del provider_id, query, modes, max_upstream_calls, config_loader
        raise DeepSeekSmokeQualificationError() from None

    credential = _select_official_provider(config_loader)
    del provider_id, query, modes, max_upstream_calls, config_loader
    if credential is None:
        del credential
        raise DeepSeekSmokeQualificationError() from None
    result = QualifiedDeepSeekProvider(credential)
    del credential
    return result


__all__ = [
    "CallAdmission",
    "DeepSeekSmokeCallAdmissionError",
    "DeepSeekSmokeQualificationError",
    "QualifiedDeepSeekProvider",
    "SMOKE_MAX_UPSTREAM_CALLS",
    "SMOKE_MODES",
    "SMOKE_PROVIDER_ID",
    "SMOKE_QUERY",
    "qualify_deepseek_provider",
]
