"""Fail-closed gate for live Codex/provider calls."""

from __future__ import annotations

import os

LIVE_CALL_APPROVAL_ENV = "CODEX_ROSETTA_ALLOW_LIVE_CALLS"
LIVE_CALL_APPROVAL_VALUE = "I_UNDERSTAND_REAL_API_CALLS"


def require_live_call_approval() -> None:
    """Require an explicit, non-secret developer opt-in before live calls."""
    if os.environ.get(LIVE_CALL_APPROVAL_ENV) != LIVE_CALL_APPROVAL_VALUE:
        raise RuntimeError(
            "live API calls are disabled by default; set "
            f"{LIVE_CALL_APPROVAL_ENV}={LIVE_CALL_APPROVAL_VALUE} "
            "only after developer approval"
        )
