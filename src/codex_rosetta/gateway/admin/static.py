"""Load the built Admin SPA from package resources."""

from __future__ import annotations

import importlib.resources
import json
import posixpath
from dataclasses import dataclass
from functools import lru_cache
from pathlib import PurePosixPath
from typing import Any


_MIME_TYPES = {
    ".css": "text/css; charset=utf-8",
    ".js": "text/javascript; charset=utf-8",
    ".json": "application/json; charset=utf-8",
    ".png": "image/png",
    ".svg": "image/svg+xml",
    ".woff": "font/woff",
    ".woff2": "font/woff2",
}


@dataclass(frozen=True)
class AdminAsset:
    """One immutable asset from the generated Vite manifest."""

    body: bytes
    content_type: str


def _dist_files() -> Any:
    """Return the Admin distribution package resource directory."""
    return importlib.resources.files(__package__ or __name__).joinpath("dist")


@lru_cache(maxsize=1)
def _asset_allowlist() -> frozenset[str]:
    """Return generated asset paths referenced by the Vite manifest."""
    manifest = json.loads(_dist_files().joinpath("manifest.json").read_text("utf-8"))
    if not isinstance(manifest, dict) or not manifest:
        raise ValueError("Admin Vite manifest must contain a non-empty object")
    allowed: set[str] = set()
    for entry in manifest.values():
        if not isinstance(entry, dict):
            raise ValueError("Admin Vite manifest entries must be objects")
        file_value = entry.get("file")
        if isinstance(file_value, str):
            allowed.add(file_value)
        for field in ("css", "assets"):
            values = entry.get(field, [])
            if not isinstance(values, list) or not all(
                isinstance(value, str) for value in values
            ):
                raise ValueError(f"Admin Vite manifest {field!r} must be a list")
            allowed.update(values)
    return frozenset(allowed)


@lru_cache(maxsize=1)
def load_admin_html() -> str:
    """Return the generated Admin SPA document bundled with this package."""
    html = _dist_files().joinpath("admin.html").read_text("utf-8")
    if '<script type="module"' not in html or "/admin/assets/" not in html:
        raise ValueError("Admin distribution entry point is incomplete")
    return html


@lru_cache(maxsize=32)
def load_admin_asset(asset_path: str) -> AdminAsset:
    """Load an allowlisted generated asset without filesystem traversal."""
    relative = asset_path.lstrip("/")
    normalized = posixpath.normpath(relative)
    path = PurePosixPath(normalized)
    if normalized != relative or path.is_absolute() or ".." in path.parts:
        raise FileNotFoundError("Invalid Admin asset path")
    if normalized not in _asset_allowlist() or not normalized.startswith("assets/"):
        raise FileNotFoundError("Unknown Admin asset")
    content_type = _MIME_TYPES.get(path.suffix.lower())
    if content_type is None:
        raise FileNotFoundError("Unsupported Admin asset type")
    resource = _dist_files()
    for part in path.parts:
        resource = resource.joinpath(part)
    return AdminAsset(resource.read_bytes(), content_type)
