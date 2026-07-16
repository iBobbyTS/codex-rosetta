"""Per-request marker for Codex configuration changes made by Admin routes."""

from __future__ import annotations

from contextvars import ContextVar


_codex_restart_required: ContextVar[bool] = ContextVar(
    "codex_restart_required", default=False
)


def reset_codex_restart_required() -> None:
    """Clear any restart marker in the current request context."""
    _codex_restart_required.set(False)


def mark_codex_restart_required() -> None:
    """Mark the current successful Admin mutation as requiring a Codex restart."""
    _codex_restart_required.set(True)


def consume_codex_restart_required() -> bool:
    """Return and clear the current request's restart marker."""
    required = _codex_restart_required.get()
    _codex_restart_required.set(False)
    return required
