"""Sub2API credential parsing for the Admin account flow."""

from __future__ import annotations

import base64
import json
from typing import Any


def _decode_jwt_payload(token: str) -> dict[str, Any]:
    try:
        segment = token.split(".")[1]
        segment += "=" * (-len(segment) % 4)
        payload = json.loads(base64.urlsafe_b64decode(segment.encode()))
    except IndexError, ValueError, TypeError, json.JSONDecodeError:
        return {}
    return payload if isinstance(payload, dict) else {}


def parse_sub2api_credentials(
    raw: object, base_url: object
) -> tuple[str, dict[str, str], dict[str, str]]:
    """Validate exported Sub2API JSON and return identity, metadata, credentials."""
    if not isinstance(base_url, str) or not base_url.strip():
        raise ValueError("Sub2API URL 不能为空")
    normalized_url = base_url.strip().rstrip("/")
    if not normalized_url.startswith(("http://", "https://")):
        normalized_url = f"https://{normalized_url}"
    if not isinstance(raw, dict):
        raise ValueError("Sub2API 认证信息必须是 JSON 对象")
    access_token = raw.get("access_token")
    refresh_token = raw.get("refresh_token")
    expires_at = raw.get("expires_at")
    if (
        not isinstance(access_token, str)
        or not access_token.strip()
        or not isinstance(refresh_token, str)
        or not refresh_token.strip()
        or expires_at is None
        or not str(expires_at).strip()
    ):
        raise ValueError(
            "Sub2API 认证信息缺少 access_token、refresh_token 或 expires_at"
        )
    claims = _decode_jwt_payload(access_token)
    email = claims.get("email")
    if not isinstance(email, str) or "@" not in email.strip():
        raise ValueError("无法从 Sub2API access_token 可靠解析邮箱")
    credentials = {
        "base_url": normalized_url,
        "access_token": access_token.strip(),
        "refresh_token": refresh_token.strip(),
        "expires_at": str(expires_at).strip(),
    }
    return email.strip().lower(), {"email": email.strip()}, credentials
