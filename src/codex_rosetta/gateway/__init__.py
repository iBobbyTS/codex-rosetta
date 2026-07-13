"""codex-rosetta Gateway — HTTP proxy/translator between LLM provider formats.

Usage::

    # CLI entry point (after pip install)
    codex-rosetta-gateway --config /path/to/config-directory

    # Module invocation
    python -m codex_rosetta.gateway --config /path/to/config-directory

    # Programmatic usage
    from codex_rosetta.gateway import create_app, GatewayConfig, load_config

    raw = load_config("config.jsonc")
    app = create_app(GatewayConfig(raw))
"""

# httpserver and httpclient are vendored in _vendor/ — no external deps needed.

from .app import create_app
from .cli import main
from .config import GatewayConfig, discover_config, load_config
from .proxy import ProviderMetadataStore

__all__ = [
    "ProviderMetadataStore",
    "create_app",
    "main",
    "GatewayConfig",
    "discover_config",
    "load_config",
]
