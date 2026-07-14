"""Load the admin panel HTML from package resources."""

from __future__ import annotations

import importlib.resources
import json
from importlib.resources.abc import Traversable


_I18N_PLACEHOLDER = "__CODEX_ROSETTA_ADMIN_I18N_JSON__"


def _load_admin_i18n(package_files: Traversable) -> dict[str, dict[str, str]]:
    """Load and validate the bundled Admin localization dictionary."""
    value = json.loads(package_files.joinpath("admin_i18n.json").read_text("utf-8"))
    if not isinstance(value, dict) or not value:
        raise ValueError("admin_i18n.json must contain a non-empty JSON object")
    for language, translations in value.items():
        if not isinstance(language, str) or not isinstance(translations, dict):
            raise ValueError("admin_i18n.json languages must map to JSON objects")
        if not all(
            isinstance(key, str) and isinstance(text, str)
            for key, text in translations.items()
        ):
            raise ValueError("admin_i18n.json translations must be strings")
    return value


def load_admin_html() -> str:
    """Return the contents of ``admin.html`` bundled with this package."""
    package_files = importlib.resources.files(__package__ or __name__)
    html = package_files.joinpath("admin.html").read_text("utf-8")
    if html.count(_I18N_PLACEHOLDER) != 1:
        raise ValueError("admin.html must contain exactly one I18N placeholder")
    serialized_i18n = json.dumps(
        _load_admin_i18n(package_files),
        ensure_ascii=True,
        separators=(",", ":"),
    ).replace("<", "\\u003c")
    return html.replace(_I18N_PLACEHOLDER, serialized_i18n)
