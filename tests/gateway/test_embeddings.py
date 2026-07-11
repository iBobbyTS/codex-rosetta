"""Tests for the embeddings passthrough handler."""

from __future__ import annotations

import asyncio
import json
import threading
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

import codex_rosetta.gateway.embeddings as embeddings_module
from codex_rosetta.gateway.config import GatewayConfig
from codex_rosetta.gateway.embeddings import handle_embeddings
from codex_rosetta.gateway.headers import MAX_REQUEST_ID_BYTES
from codex_rosetta.gateway.transport._base import UpstreamResponse
from codex_rosetta.gateway.transport.http import HttpTransport


# ---------------------------------------------------------------------------
# Fake upstream server that echoes back the received model name
# ---------------------------------------------------------------------------


class _EchoEmbeddingHandler(BaseHTTPRequestHandler):
    """Returns an embedding response that echoes the request model name."""

    def log_message(self, format, *args):  # noqa: A002
        pass

    def do_POST(self):
        length = int(self.headers.get("Content-Length", 0))
        body = json.loads(self.rfile.read(length)) if length else {}
        model = body.get("model", "")
        response = {
            "object": "list",
            "data": [
                {
                    "object": "embedding",
                    "embedding": [0.1, 0.2, 0.3],
                    "index": 0,
                }
            ],
            "model": model,
            "usage": {"prompt_tokens": 5, "total_tokens": 5},
        }
        payload = json.dumps(response).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)


@pytest.fixture(scope="module")
def echo_embedding_server():
    """Start a local server that echoes the model name in embedding responses."""
    server = ThreadingHTTPServer(("127.0.0.1", 0), _EchoEmbeddingHandler)
    port = server.server_address[1]
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{port}"
    server.shutdown()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_config(base_url: str, upstream_model: str | None = None) -> GatewayConfig:
    """Build a minimal GatewayConfig for embedding tests."""
    model_entry: dict[str, Any] = {
        "provider": "test-provider",
        "capabilities": ["embedding"],
    }
    if upstream_model:
        model_entry["upstream_model"] = upstream_model

    raw = {
        "providers": {
            "test-provider": {
                "api_key": "test-key",
                "base_url": base_url,
                "type": "openai",
            }
        },
        "models": {
            "my-embed": model_entry,
        },
        "server": {
            "admin_password": "test-admin-password",
            "api_keys": [
                {
                    "id": "test-client",
                    "label": "Test client",
                    "key": "test-gateway-key",
                }
            ],
        },
    }
    return GatewayConfig(raw)


def _make_request(
    body: dict[str, Any],
    *,
    headers: dict[str, str] | None = None,
) -> MagicMock:
    """Create a mock HTTP request with the given JSON body."""
    req = MagicMock()
    req.json.return_value = body
    req.headers = headers or {}

    # Provide app-level attributes that handle_embeddings accesses
    app = MagicMock()
    app.metrics = None
    app.request_log = None
    app.transport = HttpTransport()
    req.app = app
    return req


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestEmbeddingUpstreamModel:
    """Tests for upstream_model substitution in embedding requests."""

    @pytest.fixture(autouse=True)
    def _clear_transport(self):
        """Ensure fresh transport state between tests."""
        yield

    def test_upstream_model_substituted(self, echo_embedding_server: str):
        """When upstream_model is configured, the body sent to upstream should
        contain the upstream model name, not the gateway alias."""
        config = _make_config(echo_embedding_server, upstream_model="BAAI/bge-m3")
        request = _make_request({"model": "my-embed", "input": "hello"})

        response = asyncio.run(handle_embeddings(request, config))

        body = json.loads(response.body)
        # The echo server returns the model it received — should be the upstream name
        assert body["model"] == "BAAI/bge-m3"

    def test_no_upstream_model(self, echo_embedding_server: str):
        """When no upstream_model is configured, the original model name is used."""
        config = _make_config(echo_embedding_server, upstream_model=None)
        request = _make_request({"model": "my-embed", "input": "hello"})

        response = asyncio.run(handle_embeddings(request, config))

        body = json.loads(response.body)
        assert body["model"] == "my-embed"

    def test_user_agent_forwarded_to_passthrough_transport(self):
        """Embeddings passthrough should preserve the client's User-Agent."""
        config = _make_config("https://api.example.com/v1")
        request = _make_request(
            {"model": "my-embed", "input": "hello"},
            headers={"user-agent": "codex-cli/1.2.3"},
        )
        request.app.transport = MagicMock()
        request.app.transport.send_passthrough = AsyncMock(
            return_value=UpstreamResponse(
                status_code=200,
                body={"object": "list", "data": [], "model": "my-embed"},
                raw_content=b'{"object":"list","data":[],"model":"my-embed"}',
            )
        )

        response = asyncio.run(handle_embeddings(request, config))

        assert response.status_code == 200
        _, kwargs = request.app.transport.send_passthrough.call_args
        assert kwargs["extra_headers"]["User-Agent"] == "codex-cli/1.2.3"

    @pytest.mark.parametrize(
        ("headers", "expected_request_id"),
        [({}, None), ({"x-request-id": "r" * MAX_REQUEST_ID_BYTES}, "exact")],
    )
    def test_request_id_is_generated_or_accepts_exact_limit(
        self,
        headers: dict[str, str],
        expected_request_id: str | None,
    ) -> None:
        config = _make_config("https://api.example.com/v1")
        request = _make_request(
            {"model": "my-embed", "input": "hello"}, headers=headers
        )
        request.app.transport = MagicMock()
        request.app.transport.send_passthrough = AsyncMock(
            return_value=UpstreamResponse(
                status_code=200,
                body={"object": "list", "data": [], "model": "my-embed"},
                raw_content=b'{"object":"list","data":[],"model":"my-embed"}',
            )
        )

        response = asyncio.run(handle_embeddings(request, config))

        assert response.status_code == 200
        _, kwargs = request.app.transport.send_passthrough.call_args
        forwarded = kwargs["extra_headers"]["x-request-id"]
        if expected_request_id == "exact":
            assert forwarded == "r" * MAX_REQUEST_ID_BYTES
        else:
            uuid.UUID(forwarded)

    @pytest.mark.parametrize(
        "request_id",
        ["", " ", "req\x1b[2J", "req\x7f", "请求", "r" * (MAX_REQUEST_ID_BYTES + 1)],
    )
    def test_invalid_request_id_is_rejected_before_embeddings_side_effects(
        self,
        request_id: str,
    ) -> None:
        config = _make_config("https://api.example.com/v1")
        request = _make_request(
            {"model": "my-embed", "input": "hello"},
            headers={"x-request-id": request_id},
        )
        request.app.persistence = MagicMock()
        request.json.side_effect = AssertionError("body must remain unread")

        response = asyncio.run(handle_embeddings(request, config))

        assert response.status_code == 400
        payload = json.loads(response.body)
        assert payload["error"]["type"] == "invalid_request_error"
        assert payload["error"]["message"].startswith("'x-request-id' must be")
        request.json.assert_not_called()
        assert request.app.persistence.mock_calls == []

    def test_request_stats_use_resolved_upstream_model(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Embeddings contribute to per-model stats using the upstream name."""
        config = _make_config(
            "https://api.example.com/v1", upstream_model="BAAI/bge-m3"
        )
        request = _make_request({"model": "my-embed", "input": "hello"})
        request.app.transport = MagicMock()
        request.app.transport.send_passthrough = AsyncMock(
            return_value=UpstreamResponse(
                status_code=200,
                body={"object": "list", "data": [], "model": "BAAI/bge-m3"},
                raw_content=b'{"object":"list","data":[],"model":"BAAI/bge-m3"}',
            )
        )
        recorded_models: list[str] = []
        monkeypatch.setattr(
            embeddings_module, "record_request_stat", recorded_models.append
        )

        response = asyncio.run(handle_embeddings(request, config))

        assert response.status_code == 200
        assert recorded_models == ["BAAI/bge-m3"]
