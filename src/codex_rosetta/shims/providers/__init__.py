"""Provider shim loading — built-in directory scan + plugin entry points.

Shim lifecycle
--------------
**Registration** (startup, once):

1. ``load_providers()`` scans the built-in ``providers/`` directory via
   ``load_providers_from_dir()``, registering each shim found.
2. It then discovers ``codex_rosetta.shim_providers`` entry points and
   calls each plugin callable, which may register additional shims.

**Usage** (per request):

- ``get_shim(name)`` looks up a registered shim by name.
- The gateway / ``convert()`` injects the shim's reasoning config
  and applies transforms around the converter.

Directory layout
----------------
Each subdirectory that contains a ``provider.yaml`` is treated as a leaf
provider definition.  An optional ``transforms.py`` alongside the YAML
may export ``to_transforms`` and/or ``from_transforms`` tuples.

**Grouped directories** are also supported: a child directory that does
NOT contain ``provider.yaml`` but DOES contain subdirectories with one is
treated as a *group folder* when its children contain provider definitions.

Plugin shims
------------
Downstream packages register shims via entry points::

    # pyproject.toml
    [project.entry-points."codex_rosetta.shim_providers"]
    my_provider = "my_package.shims:register_shims"

The callable receives no arguments.  Most plugins simply call
``load_providers_from_dir()`` to scan their own YAML directory::

    from pathlib import Path
    from codex_rosetta.shims import load_providers_from_dir

    def register_shims():
        return load_providers_from_dir(Path(__file__).parent / "providers")

For advanced use cases (conditional registration, dynamic shims),
call ``register_shim()`` directly instead of scanning a directory.
The callable may optionally return ``list[ProviderShim]`` for inclusion
in ``load_providers()``'s combined result.
"""

from __future__ import annotations

import importlib.util
import logging
from collections.abc import Mapping
from functools import cache
from importlib.metadata import entry_points
from pathlib import Path
from types import MappingProxyType

from codex_rosetta._vendor.yaml import load as yaml_load

from ..provider_shim import ProviderShim, ReasoningCapability, register_shim

logger = logging.getLogger(__name__)

_PROVIDERS_DIR = Path(__file__).parent


def _load_transforms(
    provider_dir: Path, *, group: str | None = None, _builtin: bool = True
) -> tuple[tuple, tuple, tuple]:
    """Import transforms.py if present, return (from_transforms, to_transforms, ir_transforms).

    Args:
        provider_dir: Path to the leaf provider directory.
        group: Name of the parent group folder, if this is a grouped shim.
        _builtin: Whether this is a built-in provider directory.  Plugin
            transforms use a separate module namespace to avoid collisions
            with built-in modules in ``sys.modules``.
    """
    tf_path = provider_dir / "transforms.py"
    if not tf_path.exists():
        return (), (), ()
    prefix = (
        "codex_rosetta.shims.providers" if _builtin else "_codex_rosetta_plugin_shims"
    )
    if group is not None:
        module_name = f"{prefix}.{group}.{provider_dir.name}.transforms"
    else:
        module_name = f"{prefix}.{provider_dir.name}.transforms"
    spec = importlib.util.spec_from_file_location(module_name, tf_path)
    if spec is None or spec.loader is None:
        logger.warning("Could not load %s", tf_path)
        return (), (), ()
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return (
        getattr(mod, "from_transforms", ()),
        getattr(mod, "to_transforms", ()),
        getattr(mod, "ir_transforms", ()),
    )


def _load_single_provider(
    provider_dir: Path,
    *,
    group: str | None = None,
    _builtin: bool = True,
    register: bool = True,
) -> ProviderShim | None:
    """Load a single provider from *provider_dir* and register it.

    Args:
        provider_dir: Directory containing ``provider.yaml``.
        group: Name of the parent group folder (``None`` for top-level shims).
        _builtin: Whether this is a built-in provider directory.

    Returns:
        The registered :class:`ProviderShim`, or ``None`` on failure.
    """
    yaml_path = provider_dir / "provider.yaml"
    with open(yaml_path, encoding="utf-8") as f:
        cfg = yaml_load(f.read())
    if not isinstance(cfg, dict) or "name" not in cfg or "base" not in cfg:
        logger.warning("Skipping %s: missing 'name' or 'base'", yaml_path)
        return None

    from_t, to_t, ir_t = _load_transforms(provider_dir, group=group, _builtin=_builtin)

    # Parse optional reasoning capability config from YAML.
    reasoning_cfg = cfg.get("reasoning")
    reasoning_cap: ReasoningCapability | None = None
    if isinstance(reasoning_cfg, dict):
        reasoning_cap = ReasoningCapability(
            disabled=reasoning_cfg.get("disabled", "omit"),
            effort_field=reasoning_cfg.get("effort_field", "reasoning_effort"),
            max_effort=reasoning_cfg.get("max_effort"),
            thinking_type=reasoning_cfg.get("thinking_type"),
            unsigned_reasoning_blocks=reasoning_cfg.get(
                "unsigned_reasoning_blocks", "as_is"
            ),
            effort_map=reasoning_cfg.get("effort_map", {}),
            budget_tokens_default_ratio=reasoning_cfg.get(
                "budget_tokens_default_ratio"
            ),
        )

    if isinstance(reasoning_cfg, dict) and "model_overrides" in reasoning_cfg:
        raise ValueError(
            f"{yaml_path}: reasoning.model_overrides is unsupported; "
            "model identity cannot select provider request fields"
        )

    shim = ProviderShim(
        name=cfg["name"],
        base=cfg["base"],
        default_base_url=cfg.get("default_base_url"),
        default_api_key_env=cfg.get("default_api_key_env"),
        logo=cfg.get("logo"),
        model_id_field=cfg.get("model_id_field"),
        from_transforms=from_t,
        to_transforms=to_t,
        ir_transforms=ir_t,
        reasoning=reasoning_cap,
    )
    if register:
        register_shim(shim)
        logger.debug("Registered provider shim: %s (base=%s)", shim.name, shim.base)
    return shim


def load_providers_from_dir(
    providers_dir: Path, *, group: str | None = None, register: bool = True
) -> list[ProviderShim]:
    """Scan *providers_dir* for provider shims and register them.

    This is the public entry point for loading shims from an arbitrary
    directory.  Downstream packages (e.g. argo-proxy) can call this to
    load their own shim directories alongside the built-in ones.

    Plugin transforms use a separate module namespace
    (``_codex_rosetta_plugin_shims.*``) to avoid collisions with built-in
    modules in ``sys.modules``.

    Supports two layouts:

    * **Flat** — a direct child with ``provider.yaml`` (e.g. ``openai/``).
    * **Grouped** — a child WITHOUT ``provider.yaml`` whose own children
      each contain one.

    Args:
        providers_dir: Root directory to scan for provider subdirectories.
        group: Optional group name prefix for all shims loaded from this
            directory.  When ``None``, the directory structure determines
            grouping automatically.

    Returns:
        List of registered :class:`ProviderShim` instances.
    """
    builtin = providers_dir == _PROVIDERS_DIR
    shims: list[ProviderShim] = []
    for d in sorted(providers_dir.iterdir()):
        if not d.is_dir() or d.name.startswith(("_", ".")):
            continue
        yaml_path = d / "provider.yaml"
        if yaml_path.exists():
            shim = _load_single_provider(
                d, group=group, _builtin=builtin, register=register
            )
            if shim is not None:
                shims.append(shim)
        else:
            # Potential group folder — scan children.
            child_group = f"{group}.{d.name}" if group else d.name
            for sub in sorted(d.iterdir()):
                if not sub.is_dir() or sub.name.startswith(("_", ".")):
                    continue
                if (sub / "provider.yaml").exists():
                    shim = _load_single_provider(
                        sub,
                        group=child_group,
                        _builtin=builtin,
                        register=register,
                    )
                    if shim is not None:
                        shims.append(shim)
    return shims


@cache
def _builtin_provider_shims_for(
    providers_dir: Path,
) -> Mapping[str, ProviderShim]:
    """Load an immutable shim mapping for one built-in provider directory."""

    loaded = load_providers_from_dir(providers_dir, register=False)
    return MappingProxyType({shim.name: shim for shim in loaded})


def builtin_provider_shims() -> Mapping[str, ProviderShim]:
    """Return immutable built-in shims independent of the plugin registry."""

    return _builtin_provider_shims_for(_PROVIDERS_DIR)


def get_builtin_provider_shim(name: str) -> ProviderShim | None:
    """Return one immutable built-in provider shim."""

    return builtin_provider_shims().get(name)


def load_providers() -> list[ProviderShim]:
    """Load built-in provider shims and any plugin shims.

    1. Scans the built-in ``providers/`` directory.
    2. Discovers entry points in the ``codex_rosetta.shim_providers`` group
       and calls each one to let plugins register their own shims.

    Returns:
        Combined list of all registered :class:`ProviderShim` instances
        (built-in + plugin).
    """
    # 1. Built-ins come from the immutable cached mapping and never enter the
    # mutable plugin registry.
    shims = list(builtin_provider_shims().values())

    # 2. Plugin shims via entry points
    shims.extend(_load_plugin_shims())

    return shims


def _load_plugin_shims() -> list[ProviderShim]:
    """Discover and invoke ``codex_rosetta.shim_providers`` entry points.

    Each entry point should be a callable that registers shims via
    :func:`register_shim` when called (no arguments).  The callable may
    optionally return a ``list[ProviderShim]`` for inclusion in the
    combined result of :func:`load_providers`.

    Errors in individual plugins are logged and do not prevent other
    plugins from loading.
    """
    registered: list[ProviderShim] = []

    eps = entry_points()
    # Python 3.12+: eps.select(); Python 3.10–3.11: dict-style
    if hasattr(eps, "select"):
        plugin_eps = eps.select(group="codex_rosetta.shim_providers")
    else:
        plugin_eps = eps.get("codex_rosetta.shim_providers", [])

    for ep in plugin_eps:
        try:
            loader = ep.load()
            result = loader()
            if isinstance(result, list):
                registered.extend(result)
            logger.info("Loaded plugin shims from entry point: %s", ep.name)
        except Exception:
            logger.warning(
                "Failed to load plugin shim entry point: %s", ep.name, exc_info=True
            )

    return registered
