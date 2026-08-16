"""Bounded Responses request-encoding detection for one draft endpoint."""

from __future__ import annotations

import asyncio
import json
from dataclasses import asdict, dataclass
from typing import Any

from ..transport import ProviderInfo, UpstreamTransport


@dataclass(frozen=True, slots=True)
class EncodingProbeResult:
    """Outcome of one identity or Zstd streaming probe."""

    ok: bool
    status_code: int | None = None
    error: str | None = None


@dataclass(frozen=True, slots=True)
class RequestEncodingDetectionResult:
    """Two-probe result and the draft policy selected by its success matrix."""

    selected: str | None
    identity: EncodingProbeResult
    zstd: EncodingProbeResult

    def to_dict(self) -> dict[str, Any]:
        """Return the stable Admin JSON payload."""
        return {
            "selected": self.selected,
            "identity": asdict(self.identity),
            "zstd": asdict(self.zstd),
        }


async def _probe_responses_completion(
    transport: UpstreamTransport,
    provider_info: ProviderInfo,
    model: str,
) -> EncodingProbeResult:
    """Send one minimal streaming Responses request and require completion."""
    try:
        stream = await transport.send_streaming(
            provider_info,
            "openai_responses",
            {"model": model, "input": "hi", "stream": True},
            model,
        )
        async with stream:
            if stream.is_error:
                error = await stream.read_error()
                return EncodingProbeResult(
                    ok=False,
                    status_code=stream.status_code,
                    error=f"HTTP {stream.status_code}: {error}",
                )
            async for event in stream:
                event_type = event.get("type")
                if event_type == "response.completed":
                    return EncodingProbeResult(
                        ok=True,
                        status_code=stream.status_code,
                    )
                if event_type == "response.failed":
                    payload = json.dumps(
                        event,
                        ensure_ascii=False,
                        separators=(",", ":"),
                    )
                    return EncodingProbeResult(
                        ok=False,
                        status_code=stream.status_code,
                        error=f"response.failed: {payload}",
                    )
            return EncodingProbeResult(
                ok=False,
                status_code=stream.status_code,
                error="Upstream stream ended before response.completed",
            )
    except asyncio.CancelledError:
        raise
    except Exception as exc:
        message = str(exc) or type(exc).__name__
        return EncodingProbeResult(ok=False, error=message)


async def detect_responses_request_encoding(
    transport: UpstreamTransport,
    *,
    identity_provider: ProviderInfo,
    zstd_provider: ProviderInfo,
    model: str,
) -> RequestEncodingDetectionResult:
    """Run exactly one identity and one Zstd probe and select a draft policy."""
    identity, zstd = await asyncio.gather(
        _probe_responses_completion(transport, identity_provider, model),
        _probe_responses_completion(transport, zstd_provider, model),
    )
    if identity.ok and zstd.ok:
        selected = "passthrough"
    elif identity.ok:
        selected = "identity"
    elif zstd.ok:
        selected = "zstd"
    else:
        selected = None
    return RequestEncodingDetectionResult(
        selected=selected,
        identity=identity,
        zstd=zstd,
    )
