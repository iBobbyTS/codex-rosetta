"""ChatGPT OAuth PKCE callback and initial account metadata handling."""

from __future__ import annotations

import asyncio
import base64
import hashlib
import html
import json
import secrets
import socket
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from http import HTTPStatus
from typing import Any

from codex_rosetta._vendor.httpserver import JSONResponse, Request, Response

from .account_store import get_account_store

CLIENT_ID = "app_EMoamEEZ73f0CkXaXp7hrann"
AUTH_ENDPOINT = "https://auth.openai.com/oauth/authorize"
TOKEN_ENDPOINT = "https://auth.openai.com/oauth/token"
METADATA_ENDPOINT = "https://chatgpt.com/backend-api/accounts/check/v4-2023-04-27"
SCOPES = "openid profile email offline_access api.connectors.read api.connectors.invoke"
CALLBACK_PATH = "/auth/callback"
CALLBACK_PORT = 1455
LOGIN_TIMEOUT_SECONDS = 300


@dataclass
class PendingOAuth:
    verifier: str
    redirect_uri: str
    expires_at: float
    # Returned to the initiating page and echoed only by the matching callback
    # window.  It is deliberately separate from OAuth state so the browser can
    # distinguish a completed transaction from a direct popup close.
    attempt_id: str = ""
    opener_origin: str = ""


def _pending(request: Any) -> tuple[dict[str, PendingOAuth], threading.RLock]:
    app = request.app
    values = getattr(app, "chatgpt_oauth_pending", None)
    lock = getattr(app, "chatgpt_oauth_pending_lock", None)
    if values is None:
        values = {}
        setattr(app, "chatgpt_oauth_pending", values)
    if lock is None:
        lock = threading.RLock()
        setattr(app, "chatgpt_oauth_pending_lock", lock)
    return values, lock


def _random_url_token() -> str:
    return secrets.token_urlsafe(32)


def _pkce_challenge(verifier: str) -> str:
    return (
        base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest())
        .rstrip(b"=")
        .decode()
    )


def _redirect_uri(request: Any) -> str:
    return f"http://localhost:{CALLBACK_PORT}{CALLBACK_PATH}"


def _opener_origin(request: Any) -> str:
    origin = request.headers.get("origin", "")
    if origin.startswith("http://localhost:"):
        return origin
    port = int(getattr(request.app, "gateway_port", 8765))
    return f"http://localhost:{port}"


def _write_callback_response(connection: socket.socket, response: Response) -> None:
    reason = HTTPStatus(response.status_code).phrase
    headers = dict(response.headers)
    headers.setdefault("Content-Length", str(len(response.body)))
    headers.setdefault("Connection", "close")
    serialized = "HTTP/1.1 {} {}\r\n{}\r\n".format(
        response.status_code,
        reason,
        "".join(f"{key}: {value}\r\n" for key, value in headers.items()),
    ).encode("latin-1")
    connection.sendall(serialized + response.body)


def _run_callback_listener(app: Any, listener: socket.socket) -> None:
    """Serve one OAuth callback on the registered localhost:1455 listener."""
    deadline = time.monotonic() + LOGIN_TIMEOUT_SECONDS
    listener.settimeout(1.0)
    try:
        while time.monotonic() < deadline:
            try:
                connection, address = listener.accept()
            except TimeoutError:
                continue
            except OSError:
                return
            with connection:
                connection.settimeout(5.0)
                raw = connection.recv(16 * 1024)
                first_line = raw.decode("utf-8", errors="replace").splitlines()[0]
                target = first_line.split(" ", 2)[1]
                parsed = urllib.parse.urlsplit(target)
                if parsed.path != CALLBACK_PATH:
                    response = _success_page("OAuth 回调路径无效。", status=400)
                else:
                    callback_request = Request(
                        "GET", parsed.path, parsed.query, {}, b"", address, app
                    )
                    try:
                        response = asyncio.run(chatgpt_callback(callback_request))
                    except Exception:
                        response = _success_page(
                            "OAuth 回调处理失败，请返回管理页面重试。", status=500
                        )
                _write_callback_response(connection, response)
            return
    finally:
        listener.close()
        if getattr(app, "chatgpt_oauth_listener", None) is listener:
            app.chatgpt_oauth_listener = None


def _authorization_url(redirect_uri: str, verifier: str, state: str) -> str:
    query = urllib.parse.urlencode(
        {
            "response_type": "code",
            "client_id": CLIENT_ID,
            "redirect_uri": redirect_uri,
            "scope": SCOPES,
            "code_challenge": _pkce_challenge(verifier),
            "code_challenge_method": "S256",
            "id_token_add_organizations": "true",
            "codex_cli_simplified_flow": "true",
            "state": state,
            "originator": "codex_vscode",
        }
    )
    return f"{AUTH_ENDPOINT}?{query}"


async def start_chatgpt_login(request: Any) -> Response:
    """Create one expiring PKCE login transaction for the authenticated Admin."""
    listener: socket.socket | None = None
    try:
        listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        listener.bind(("127.0.0.1", CALLBACK_PORT))
        listener.listen(1)
    except OSError:
        if listener is not None:
            listener.close()
        return JSONResponse(
            {
                "error": f"ChatGPT 登录回调端口 {CALLBACK_PORT} 已被占用，请关闭占用该端口的程序后重试。",
                "code": "oauth_callback_port_in_use",
            },
            status_code=409,
        )
    pending, lock = _pending(request)
    now = time.monotonic()
    verifier = _random_url_token()
    state = _random_url_token()
    redirect_uri = _redirect_uri(request)
    with lock:
        for key, value in list(pending.items()):
            if value.expires_at <= now:
                pending.pop(key, None)
        pending[state] = PendingOAuth(
            verifier=verifier,
            redirect_uri=redirect_uri,
            expires_at=now + LOGIN_TIMEOUT_SECONDS,
            attempt_id=state,
            opener_origin=_opener_origin(request),
        )
    request.app.chatgpt_oauth_listener = listener
    threading.Thread(
        target=_run_callback_listener,
        args=(request.app, listener),
        name="chatgpt-oauth-callback",
        daemon=True,
    ).start()
    return JSONResponse(
        {
            "authorization_url": _authorization_url(redirect_uri, verifier, state),
            "expires_in": LOGIN_TIMEOUT_SECONDS,
            "attempt_id": state,
        }
    )


def _decode_jwt(token: str) -> dict[str, Any]:
    try:
        segment = token.split(".")[1]
        segment += "=" * (-len(segment) % 4)
        value = json.loads(base64.urlsafe_b64decode(segment.encode()))
    except IndexError, ValueError, TypeError, json.JSONDecodeError:
        return {}
    return value if isinstance(value, dict) else {}


def _first_string(*values: Any) -> str:
    for value in values:
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ""


def _claim_payload(
    access_token: str, id_token: str
) -> tuple[dict[str, Any], dict[str, Any]]:
    return _decode_jwt(access_token), _decode_jwt(id_token)


def _metadata_from_claims(access_token: str, id_token: str) -> dict[str, str]:
    access, identity = _claim_payload(access_token, id_token)
    auth = access.get("https://api.openai.com/auth")
    if not isinstance(auth, dict):
        auth = identity.get("https://api.openai.com/auth")
    if not isinstance(auth, dict):
        auth = {}
    organizations = auth.get("organizations") or identity.get("organizations")
    workspace = ""
    if isinstance(organizations, list) and organizations:
        first = organizations[0]
        if isinstance(first, dict):
            workspace = _first_string(
                first.get("name"),
                first.get("display_name"),
                first.get("organization_name"),
            )
        else:
            workspace = _first_string(first)
    email = _first_string(identity.get("email"), access.get("email"))
    name = _first_string(identity.get("name"), identity.get("preferred_username"))
    account_id = _first_string(auth.get("account_id"), identity.get("account_id"))
    plan = _first_string(
        auth.get("chatgpt_plan_type"), identity.get("chatgpt_plan_type")
    )
    return {
        "name": name or (email.split("@", 1)[0] if email else ""),
        "email": email,
        "workspace": workspace,
        "subscription_type": plan,
        "account_id": account_id,
    }


def _metadata_request(access_token: str, account_id: str) -> dict[str, str]:
    headers = {"Authorization": f"Bearer {access_token}", "Accept": "application/json"}
    if account_id:
        headers["ChatGPT-Account-Id"] = account_id
    request = urllib.request.Request(METADATA_ENDPOINT, headers=headers)
    try:
        with urllib.request.urlopen(request, timeout=15) as response:
            if response.status < 200 or response.status >= 300:
                return {}
            data = json.loads(response.read().decode("utf-8"))
    except OSError, ValueError, urllib.error.URLError:
        return {}
    if not isinstance(data, dict):
        return {}

    records = data.get("accounts")
    if isinstance(records, dict):
        records = list(records.values())
    if not isinstance(records, list):
        records = []
    records = [record for record in records if isinstance(record, dict)]
    if not records:
        return {}

    selected = records[0]
    if account_id:
        for record in records:
            account = record.get("account")
            if not isinstance(account, dict):
                continue
            candidates = (
                account.get("account_id"),
                account.get("id"),
                account.get("chatgpt_account_id"),
                account.get("workspace_id"),
            )
            if account_id in candidates:
                selected = record
                break

    account = selected.get("account")
    entitlement = selected.get("entitlement")
    if not isinstance(account, dict):
        return {}
    if not isinstance(entitlement, dict):
        entitlement = {}
    return {
        "name": _first_string(
            account.get("name"),
            account.get("display_name"),
            account.get("account_name"),
            account.get("organization_name"),
            account.get("workspace_name"),
            account.get("title"),
        ),
        "email": _first_string(account.get("email")),
        "workspace": _first_string(
            account.get("structure"),
            account.get("account_structure"),
            account.get("kind"),
            account.get("type"),
            account.get("account_type"),
            account.get("workspace_name"),
            account.get("organization_name"),
        ),
        "subscription_type": _first_string(
            entitlement.get("subscription_plan"),
            account.get("plan_type"),
            account.get("planType"),
        ),
    }


def exchange_code(code: str, verifier: str, redirect_uri: str) -> dict[str, Any]:
    """Exchange an OAuth authorization code using the official token endpoint."""
    body = urllib.parse.urlencode(
        {
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": redirect_uri,
            "client_id": CLIENT_ID,
            "code_verifier": verifier,
        }
    ).encode()
    request = urllib.request.Request(
        TOKEN_ENDPOINT,
        data=body,
        headers={
            "Content-Type": "application/x-www-form-urlencoded",
            "Accept": "application/json",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=25) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except (OSError, ValueError, urllib.error.URLError) as exc:
        raise ValueError("OAuth Token 交换失败") from exc
    if not isinstance(payload, dict):
        raise ValueError("OAuth Token 响应无效")
    required = {
        field: payload.get(field)
        for field in ("id_token", "access_token", "refresh_token")
    }
    if any(
        not isinstance(value, str) or not value.strip() for value in required.values()
    ):
        raise ValueError("OAuth Token 响应缺少核心凭据")
    return required


def _success_page(
    message: str,
    *,
    status: int = 200,
    attempt_id: str = "",
    outcome: str = "",
    target_origin: str = "",
) -> Response:
    title = "ChatGPT 登录成功" if status < 400 else "ChatGPT 登录失败"
    completion = ""
    if attempt_id and outcome in {"saved", "failed"}:
        payload = json.dumps(
            {
                "source": "codex-rosetta-chatgpt-oauth",
                "signal": attempt_id,
                "outcome": outcome,
                "message": message,
            },
            ensure_ascii=True,
            separators=(",", ":"),
        )
        # The values above are generated by this process, but escaping `<` and
        # U+2028/U+2029 keeps the inline JSON safe if an upstream error is
        # reflected in the completion message.
        payload = (
            payload.replace("<", "\\u003c")
            .replace(">", "\\u003e")
            .replace("&", "\\u0026")
            .replace("\u2028", "\\u2028")
            .replace("\u2029", "\\u2029")
        )
        completion = (
            "<script>"
            f"window.opener&&window.opener.postMessage({payload},{json.dumps(target_origin)});"
            "window.close();"
            "</script>"
        )
    body = (
        "<!doctype html><meta charset='utf-8'><title>"
        + html.escape(title)
        + "</title><main style='font-family:system-ui;max-width:40rem;margin:15vh auto;padding:2rem'>"
        + f"<h1>{html.escape(title)}</h1><p>{html.escape(message)}</p>"
        + "<p>可以关闭此窗口并返回管理页面。</p></main>"
        + completion
    )
    return Response(
        body=body.encode(),
        status_code=status,
        content_type="text/html; charset=utf-8",
        headers={"Cache-Control": "no-store"},
    )


async def chatgpt_callback(request: Any) -> Response:
    """Consume one state/code callback and persist only a valid token result."""
    state_values = request.query_params.get("state") or []
    state = state_values[0] if state_values else ""
    pending, lock = _pending(request)
    with lock:
        transaction = pending.pop(state, None) if state else None
    if transaction is None:
        return _success_page("OAuth 回调无效或已过期。", status=400)
    if transaction.expires_at <= time.monotonic():
        return _success_page(
            "OAuth 登录已超时，请返回管理页面重试。",
            status=400,
            attempt_id=transaction.attempt_id,
            outcome="failed",
            target_origin=transaction.opener_origin,
        )
    error_values = request.query_params.get("error") or []
    if error_values:
        return _success_page(
            f"浏览器登录被拒绝：{error_values[0]}",
            status=400,
            attempt_id=transaction.attempt_id,
            outcome="failed",
            target_origin=transaction.opener_origin,
        )
    code_values = request.query_params.get("code") or []
    if not code_values or not code_values[0]:
        return _success_page(
            "OAuth 回调缺少授权码。",
            status=400,
            attempt_id=transaction.attempt_id,
            outcome="failed",
            target_origin=transaction.opener_origin,
        )
    try:
        tokens = await asyncio.to_thread(
            exchange_code,
            code_values[0],
            transaction.verifier,
            transaction.redirect_uri,
        )
        metadata = _metadata_from_claims(tokens["access_token"], tokens["id_token"])
        fetched = await asyncio.to_thread(
            _metadata_request, tokens["access_token"], metadata.get("account_id", "")
        )
        metadata = {
            **metadata,
            **{key: value for key, value in fetched.items() if value},
        }
        account_id = metadata.get("account_id", "") or metadata.get("email", "")
        if not account_id:
            raise ValueError("无法识别 ChatGPT 账号身份")
        expires_at = _decode_jwt(tokens["access_token"]).get("exp")
        credentials = {**tokens}
        if isinstance(expires_at, (int, float)):
            credentials["expires_at"] = str(expires_at)
        metadata.pop("account_id", None)
        store = get_account_store(request.app)
        await asyncio.to_thread(
            store.upsert,
            provider="chatgpt",
            identity=account_id,
            metadata=metadata,
            credentials=credentials,
        )
    except (ValueError, TypeError, KeyError) as exc:
        return _success_page(
            str(exc),
            status=400,
            attempt_id=transaction.attempt_id,
            outcome="failed",
            target_origin=transaction.opener_origin,
        )
    return _success_page(
        "账号已保存。",
        attempt_id=transaction.attempt_id,
        outcome="saved",
        target_origin=transaction.opener_origin,
    )
