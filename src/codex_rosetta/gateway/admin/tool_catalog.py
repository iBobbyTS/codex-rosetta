"""Load the immutable Admin tools catalog from package resources."""

from __future__ import annotations

import importlib.resources
import json
from functools import lru_cache
from typing import Any

from ..tool_catalog_contract import CompiledToolCatalog, compile_tool_catalog


@lru_cache(maxsize=1)
def load_tool_catalog() -> dict[str, Any]:
    """Return the bundled read-only tools catalog."""
    text = (
        importlib.resources.files(__package__ or __name__)
        .joinpath("tool_catalog.json")
        .read_text("utf-8")
    )
    catalog = json.loads(text)
    if not isinstance(catalog, dict):
        raise ValueError("tool_catalog.json must contain a JSON object")
    return catalog


@lru_cache(maxsize=1)
def load_compiled_tool_catalog() -> CompiledToolCatalog:
    """Return the validated immutable runtime contract for catalog schema v6."""
    return compile_tool_catalog(load_tool_catalog())
