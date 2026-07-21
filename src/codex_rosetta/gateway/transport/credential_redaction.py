"""Provider-return credential redaction at the transport boundary."""

from __future__ import annotations

import asyncio
import json
import re
from collections.abc import AsyncIterator
from typing import Any

from codex_rosetta.auto_detect import ProviderType
from codex_rosetta.observability.redaction import (
    SecretCollisionError,
    SecretRedactor,
    decode_json_preserving_members,
)

from ._base import (
    UpstreamConnectionError,
    UpstreamCredentialCollisionError,
    UpstreamResponse,
    UpstreamStream,
    UpstreamTransport,
)
from .credential_semantics import ProviderCredentialSemanticGate
from .provider_info import ProviderInfo


def _provider_redactor(provider_info: ProviderInfo) -> SecretRedactor:
    values = getattr(provider_info, "credential_values", ())
    if not isinstance(values, tuple | list | set | frozenset):
        values = ()
    return SecretRedactor(values)


def _sanitized_transport_error(
    provider_info: ProviderInfo,
    exc: Exception,
) -> UpstreamConnectionError:
    """Return a cause-free transport error whose message contains no provider key."""
    message = _provider_redactor(provider_info).redact_exact(str(exc))
    error_type = type(exc) if isinstance(exc, UpstreamConnectionError) else None
    try:
        error = error_type(message) if error_type is not None else None
    except TypeError:
        error = None
    if not isinstance(error, UpstreamConnectionError):
        error = UpstreamConnectionError(message)
    error.__cause__ = None
    error.__context__ = None
    return error


def _credential_collision_error() -> UpstreamCredentialCollisionError:
    """Return a stable error for an ambiguous provider-return collision."""
    return UpstreamCredentialCollisionError(
        "Upstream response contains a configured credential; response blocked"
    )


_SSE_EVENT_BOUNDARY = re.compile(rb"(?:\r\n|\r|\n)(?:\r\n|\r|\n)")


def _sse_frame_contains_credential(
    redactor: SecretRedactor,
    semantic_gate: ProviderCredentialSemanticGate,
    frame: bytes,
    *,
    initial_frame: bool,
) -> bool:
    """Check raw SSE bytes and the decoded JSON value of joined data fields."""
    if redactor.contains_wire_bytes(frame):
        return True
    data_lines: list[bytes] = []
    for index, line in enumerate(frame.splitlines()):
        if initial_frame and index == 0 and line.startswith(b"\xef\xbb\xbf"):
            line = line[3:]
        if not line.startswith(b"data:"):
            continue
        value = line[5:]
        if value.startswith(b" "):
            value = value[1:]
        data_lines.append(value)
    if not data_lines:
        return False
    data = b"\n".join(data_lines)
    if redactor.contains_json_semantic(data):
        return True
    try:
        parsed = decode_json_preserving_members(data)
    except json.JSONDecodeError, UnicodeDecodeError:
        return False
    semantic_gate.inspect_stream_event(parsed)
    return False


class _SSECredentialGate:
    """Release only complete SSE events proven free of configured credentials."""

    def __init__(
        self,
        redactor: SecretRedactor,
        target_provider: ProviderType | None,
    ) -> None:
        self._redactor = redactor
        self._semantic_gate = ProviderCredentialSemanticGate(redactor, target_provider)
        self._buffer = b""
        self._held_frame = b""
        self._finished = False
        self._initial_frame = True

    def feed(self, chunk: bytes) -> bytes:
        """Consume raw bytes while retaining one frame for cross-frame detection."""
        if self._finished:
            raise RuntimeError("SSE credential gate is already finished")

        data = self._buffer + chunk
        output: list[bytes] = []
        offset = 0
        while match := _SSE_EVENT_BOUNDARY.search(data, offset):
            frame = data[offset : match.end()]
            if self._redactor.contains_wire_bytes(
                self._held_frame + frame
            ) or _sse_frame_contains_credential(
                self._redactor,
                self._semantic_gate,
                frame,
                initial_frame=self._initial_frame,
            ):
                self._clear()
                raise SecretCollisionError
            self._initial_frame = False
            if self._held_frame:
                output.append(self._held_frame)
            self._held_frame = frame
            offset = match.end()

        self._buffer = data[offset:]
        if self._redactor.contains_wire_bytes(self._held_frame + self._buffer):
            self._clear()
            raise SecretCollisionError
        return b"".join(output)

    def finish(self) -> bytes:
        """Release the final safe frame and suffix without changing wire bytes."""
        if self._finished:
            return b""
        self._finished = True
        output = self._held_frame + self._buffer
        if self._redactor.contains_wire_bytes(output) or _sse_frame_contains_credential(
            self._redactor,
            self._semantic_gate,
            self._buffer,
            initial_frame=self._initial_frame,
        ):
            self._clear()
            raise SecretCollisionError
        self._clear()
        return output

    def _clear(self) -> None:
        self._semantic_gate.finish()
        self._held_frame = b""
        self._buffer = b""


class CredentialRedactingStream(UpstreamStream):
    """Sanitize one upstream stream before any consumer can inspect it."""

    def __init__(
        self,
        stream: UpstreamStream,
        provider_info: ProviderInfo,
        target_provider: ProviderType,
    ) -> None:
        self._stream = stream
        self._provider_info = provider_info
        self._redactor = _provider_redactor(provider_info)
        self._target_provider = target_provider
        self._semantic_gate = ProviderCredentialSemanticGate(
            self._redactor,
            target_provider,
        )

    @property
    def status_code(self) -> int:
        return self._stream.status_code

    async def __aenter__(self) -> CredentialRedactingStream:
        error: UpstreamConnectionError | None = None
        try:
            await self._stream.__aenter__()
        except Exception as exc:
            error = _sanitized_transport_error(self._provider_info, exc)
        if error is not None:
            raise error from None
        return self

    async def __aexit__(self, *args: Any) -> None:
        error: UpstreamConnectionError | None = None
        try:
            await self._stream.__aexit__(*args)
        except Exception as exc:
            error = _sanitized_transport_error(self._provider_info, exc)
        if error is not None:
            raise error from None

    async def read_error(self) -> str:
        error: UpstreamConnectionError | None = None
        try:
            value = await self._stream.read_error()
        except Exception as exc:
            error = _sanitized_transport_error(self._provider_info, exc)
            value = ""
        if error is not None:
            raise error from None
        if self._redactor.contains_json_semantic(value):
            return (
                '{"error":{"message":"Upstream response contains a configured '
                'credential; response blocked"}}'
            )
        return value

    def __aiter__(self) -> AsyncIterator[dict[str, Any]]:
        async def redacted_events() -> AsyncIterator[dict[str, Any]]:
            error: UpstreamConnectionError | None = None
            try:
                async for event in self._stream:
                    if self._redactor.contains_exact(event):
                        raise _credential_collision_error()
                    self._semantic_gate.inspect_stream_event(event)
                    yield event
                self._semantic_gate.finish()
            except asyncio.CancelledError, GeneratorExit:
                raise
            except SecretCollisionError:
                error = _credential_collision_error()
            except Exception as exc:
                error = _sanitized_transport_error(self._provider_info, exc)
            if error is not None:
                raise error from None

        return redacted_events()

    def aiter_raw_bytes(self) -> AsyncIterator[bytes] | None:
        raw_stream = self._stream.aiter_raw_bytes()
        if raw_stream is None:
            return None

        async def redacted_bytes() -> AsyncIterator[bytes]:
            gate = _SSECredentialGate(self._redactor, self._target_provider)
            error: UpstreamConnectionError | None = None
            try:
                async for chunk in raw_stream:
                    safe = gate.feed(chunk)
                    if safe:
                        yield safe
                tail = gate.finish()
                if tail:
                    yield tail
            except asyncio.CancelledError, GeneratorExit:
                raise
            except SecretCollisionError:
                error = _credential_collision_error()
            except Exception as exc:
                error = _sanitized_transport_error(self._provider_info, exc)
            if error is not None:
                raise error from None

        return redacted_bytes()

    async def close(self) -> None:
        error: UpstreamConnectionError | None = None
        try:
            close = getattr(self._stream, "close", None)
            if close is None:
                await self._stream.__aexit__(None, None, None)
            else:
                await close()
        except asyncio.CancelledError, GeneratorExit:
            raise
        except Exception as exc:
            error = _sanitized_transport_error(self._provider_info, exc)
        if error is not None:
            raise error from None


class CredentialRedactingTransport:
    """Decorate an upstream transport with provider-return credential removal."""

    def __init__(self, transport: UpstreamTransport) -> None:
        self._transport = transport

    @classmethod
    def wrap(cls, transport: UpstreamTransport) -> CredentialRedactingTransport:
        """Return one redacting layer around *transport*."""
        return transport if isinstance(transport, cls) else cls(transport)

    async def send_request(
        self,
        provider_info: ProviderInfo,
        target_provider: ProviderType,
        body: dict[str, Any],
        model: str,
        *,
        extra_headers: dict[str, str] | None = None,
    ) -> UpstreamResponse:
        error: UpstreamConnectionError | None = None
        try:
            response = await self._transport.send_request(
                provider_info,
                target_provider,
                body,
                model,
                extra_headers=extra_headers,
            )
        except Exception as exc:
            error = _sanitized_transport_error(provider_info, exc)
            response = UpstreamResponse(status_code=500, body=None, raw_content=b"")
        if error is not None:
            raise error from None
        return self._redact_response(provider_info, response, target_provider)

    async def send_streaming(
        self,
        provider_info: ProviderInfo,
        target_provider: ProviderType,
        body: dict[str, Any],
        model: str,
        *,
        extra_headers: dict[str, str] | None = None,
        wire_body: bytes | None = None,
        wire_headers: dict[str, str] | None = None,
    ) -> UpstreamStream:
        kwargs: dict[str, Any] = {"extra_headers": extra_headers}
        if wire_body is not None:
            kwargs.update(wire_body=wire_body, wire_headers=wire_headers)
        error: UpstreamConnectionError | None = None
        try:
            stream = await self._transport.send_streaming(
                provider_info,
                target_provider,
                body,
                model,
                **kwargs,
            )
        except Exception as exc:
            error = _sanitized_transport_error(provider_info, exc)
            stream = None
        if error is not None:
            raise error from None
        assert stream is not None
        return CredentialRedactingStream(stream, provider_info, target_provider)

    async def send_passthrough(
        self,
        provider_info: ProviderInfo,
        url: str,
        body: dict[str, Any],
        *,
        extra_headers: dict[str, str] | None = None,
    ) -> UpstreamResponse:
        error: UpstreamConnectionError | None = None
        try:
            response = await self._transport.send_passthrough(
                provider_info,
                url,
                body,
                extra_headers=extra_headers,
            )
        except Exception as exc:
            error = _sanitized_transport_error(provider_info, exc)
            response = UpstreamResponse(status_code=500, body=None, raw_content=b"")
        if error is not None:
            raise error from None
        return self._redact_response(provider_info, response, None)

    async def close(self) -> None:
        await self._transport.close()

    @staticmethod
    def _redact_response(
        provider_info: ProviderInfo,
        response: UpstreamResponse,
        target_provider: ProviderType | None,
    ) -> UpstreamResponse:
        redactor = _provider_redactor(provider_info)
        semantic_gate = ProviderCredentialSemanticGate(redactor, target_provider)
        if redactor.contains_exact(response.body):
            raise _credential_collision_error()
        try:
            semantic_gate.inspect_document(response.body)
        except SecretCollisionError:
            raise _credential_collision_error() from None
        if redactor.contains_json_semantic(response.raw_content):
            raise _credential_collision_error()
        try:
            parsed_raw = decode_json_preserving_members(response.raw_content)
        except json.JSONDecodeError, UnicodeDecodeError:
            parsed_raw = None
        try:
            semantic_gate.inspect_document(parsed_raw)
        except SecretCollisionError:
            raise _credential_collision_error() from None
        return UpstreamResponse(
            status_code=response.status_code,
            body=response.body,
            raw_content=response.raw_content,
        )


__all__ = ["CredentialRedactingStream", "CredentialRedactingTransport"]
