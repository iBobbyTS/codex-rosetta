"""Offline fake composition for the explicit DeepSeek search smoke CLI.

The module consumes only adjacent accepted harness primitives plus injected
configuration and client fakes. It never imports the gateway, a real client,
transport code, or runtime configuration.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import importlib.util
import json
from collections.abc import Callable, Sequence
from pathlib import Path
from types import ModuleType
from typing import Any, Final


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


def _load_evidence_contract() -> ModuleType:
    """Load the adjacent evidence primitives without importing the application."""
    path = Path(__file__).with_name("deepseek_search_evidence.py")
    spec = importlib.util.spec_from_file_location("deepseek_search_evidence", path)
    if spec is None or spec.loader is None:
        raise ImportError("DeepSeek evidence contract is unavailable") from None
    evidence_module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(evidence_module)
    return evidence_module


_EVIDENCE_CONTRACT = _load_evidence_contract()
serialize_evidence_manifest = _EVIDENCE_CONTRACT.serialize_evidence_manifest
write_private_evidence_bytes = _EVIDENCE_CONTRACT.write_private_evidence_bytes

SMOKE_PROVIDER_ID: Final = "deepseek"
SMOKE_QUERY: Final = "latest python release version"
SMOKE_MODES: Final = ("direct",)
SMOKE_MAX_UPSTREAM_CALLS: Final = 1
SMOKE_MODEL: Final = "deepseek-v4-flash"
SMOKE_MAX_OUTPUT_TOKENS: Final = 1024
SMOKE_CITATION_LIMIT: Final = 5

_QUALIFICATION_ERROR: Final = "DeepSeek search smoke qualification failed"
_ADMISSION_ERROR: Final = "DeepSeek search smoke call admission denied"
_HARNESS_ERROR: Final = "DeepSeek offline search harness failed"
_OFFLINE_FAKE_CREDENTIAL: Final = "offline-fake-credential"
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


class DeepSeekOfflineHarnessError(RuntimeError):
    """Static ordinary failure for the explicit offline fake composition."""

    def __init__(self) -> None:
        super().__init__(_HARNESS_ERROR)

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
    """Load and qualify exactly one enabled official DeepSeek provider row."""
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


def _sha256(value: str) -> str:
    """Hash one synthetic UTF-8 value for the allowlisted evidence manifest."""
    return hashlib.sha256(value.encode("utf-8", "strict")).hexdigest()


def _result_material(
    result: object,
) -> tuple[str, tuple[dict[str, str], ...], dict[str, int], str]:
    """Validate and serialize the accepted fake result shape."""
    output = getattr(result, "output")
    results = getattr(result, "results")
    usage = getattr(result, "usage")
    if type(output) is not str or not output:
        raise ValueError("invalid fake output")
    if type(results) is not tuple or not all(
        type(item) is dict
        and all(type(key) is str and type(value) is str for key, value in item.items())
        for item in results
    ):
        raise ValueError("invalid fake results")
    if (
        type(usage) is not dict
        or set(usage) != {"input_tokens", "output_tokens", "total_tokens"}
        or not all(type(value) is int for value in usage.values())
    ):
        raise ValueError("invalid fake usage")
    result_json = json.dumps(
        {"output": output, "results": results},
        ensure_ascii=False,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return output, results, usage, result_json


def _build_offline_manifest(
    result: object,
) -> tuple[dict[str, object], tuple[str, ...]]:
    """Build one exact generation-2 offline evidence manifest."""
    output, results, usage, result_json = _result_material(result)
    request_json = json.dumps(
        {
            "citation_limit": SMOKE_CITATION_LIMIT,
            "max_output_tokens": SMOKE_MAX_OUTPUT_TOKENS,
            "model": SMOKE_MODEL,
            "query": SMOKE_QUERY,
        },
        ensure_ascii=False,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    manifest: dict[str, object] = {
        "schema": "codex-rosetta.deepseek-search-evidence",
        "version": 1,
        "mode": "direct",
        "status": "completed",
        "category": "success",
        "execution": {
            "provider_family": "DEEPSEEK_NATIVE_RESPONSES",
            "execution_mode": "NATIVE_RESPONSES_HOSTED_SEARCH",
            "model": SMOKE_MODEL,
        },
        "provenance": {
            "implementation_generation": 2,
            "generation_2_live_proof": False,
            "generation_0_evidence": "referenced-only",
        },
        "hashes": {
            "request_sha256": _sha256(request_json),
            "query_sha256": _sha256(SMOKE_QUERY),
            "result_sha256": _sha256(result_json),
        },
        "counts": {
            "upstream_calls": 1,
            "search_calls": 1,
            "result_count": len(results),
            "citation_count": len(results),
        },
        "latency_ms": 0,
        "usage": dict(usage),
    }
    return manifest, (SMOKE_QUERY, output, result_json)


async def run_offline_deepseek_search_harness(
    *,
    config_loader: Callable[[], object],
    client_factory: Callable[[str, str], object],
    trusted_parent: str,
) -> Path:
    """Run one explicit fake search and publish its sanitized evidence bytes."""
    try:
        qualified = qualify_deepseek_provider(
            provider_id=SMOKE_PROVIDER_ID,
            query=SMOKE_QUERY,
            modes=list(SMOKE_MODES),
            max_upstream_calls=SMOKE_MAX_UPSTREAM_CALLS,
            config_loader=config_loader,
        )
        if (
            qualified.provider_id != SMOKE_PROVIDER_ID
            or qualified.origin != _OFFICIAL_ORIGIN
        ):
            raise ValueError("invalid qualified identity")

        admission = CallAdmission(SMOKE_MAX_UPSTREAM_CALLS)
        admission.reserve()
        client: Any = client_factory(qualified.credential, qualified.origin)
        result = await client.execute(
            SMOKE_QUERY,
            model=SMOKE_MODEL,
            max_output_tokens=SMOKE_MAX_OUTPUT_TOKENS,
            citation_limit=SMOKE_CITATION_LIMIT,
        )
        manifest, _ = _build_offline_manifest(result)
        manifest_bytes = serialize_evidence_manifest(manifest)
        return write_private_evidence_bytes(manifest_bytes, trusted_parent)
    except MemoryError:
        raise
    except Exception:
        raise DeepSeekOfflineHarnessError() from None


class _OfflineFakeResult:
    """Fixed accepted-shape result used only by the explicit offline CLI."""

    __slots__ = ("output", "results", "usage")

    def __init__(self) -> None:
        self.output = "Synthetic offline search result."
        self.results = (
            {
                "title": "Synthetic result",
                "url": "https://example.invalid/offline-result",
                "snippet": "No live provider was contacted",
            },
        )
        self.usage = {"input_tokens": 12, "output_tokens": 8, "total_tokens": 20}


class _OfflineFakeClient:
    """Socket-free fixed client used only by ``--offline-fake``."""

    async def execute(
        self,
        query: object,
        *,
        model: object,
        max_output_tokens: object,
        citation_limit: object,
    ) -> _OfflineFakeResult:
        if (
            query != SMOKE_QUERY
            or model != SMOKE_MODEL
            or max_output_tokens != SMOKE_MAX_OUTPUT_TOKENS
            or citation_limit != SMOKE_CITATION_LIMIT
        ):
            raise ValueError("invalid offline controls")
        return _OfflineFakeResult()


def _offline_config_loader() -> object:
    """Return one fixed synthetic official-provider row."""
    return {
        "providers": {
            "offline-fake": {
                "enabled": True,
                "provider": SMOKE_PROVIDER_ID,
                "base_url": _OFFICIAL_ORIGIN,
                "api_key": _OFFLINE_FAKE_CREDENTIAL,
            }
        }
    }


def _offline_client_factory(credential: str, origin: str) -> object:
    """Construct the fixed fake only after exact synthetic qualification."""
    if credential != _OFFLINE_FAKE_CREDENTIAL or origin != _OFFICIAL_ORIGIN:
        raise ValueError("invalid offline qualification")
    return _OfflineFakeClient()


def main(argv: Sequence[str] | None = None) -> int:
    """Run only the explicit offline fake composition command."""
    parser = argparse.ArgumentParser(allow_abbrev=False)
    parser.add_argument("--offline-fake", action="store_true", required=True)
    parser.add_argument("--evidence-parent", required=True)
    arguments = parser.parse_args(argv)
    final_path = asyncio.run(
        run_offline_deepseek_search_harness(
            config_loader=_offline_config_loader,
            client_factory=_offline_client_factory,
            trusted_parent=arguments.evidence_parent,
        )
    )
    print(final_path)
    return 0


__all__ = [
    "CallAdmission",
    "DeepSeekOfflineHarnessError",
    "DeepSeekSmokeCallAdmissionError",
    "DeepSeekSmokeQualificationError",
    "QualifiedDeepSeekProvider",
    "SMOKE_MAX_UPSTREAM_CALLS",
    "SMOKE_MODES",
    "SMOKE_PROVIDER_ID",
    "SMOKE_QUERY",
    "main",
    "qualify_deepseek_provider",
    "run_offline_deepseek_search_harness",
]


if __name__ == "__main__":
    raise SystemExit(main())
