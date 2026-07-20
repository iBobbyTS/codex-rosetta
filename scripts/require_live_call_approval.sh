#!/bin/bash

# Shared fail-closed gate for shell launchers that may make real provider calls.
LIVE_CALL_APPROVAL_VALUE="I_UNDERSTAND_REAL_API_CALLS"
if [ "${CODEX_ROSETTA_ALLOW_LIVE_CALLS:-}" != "$LIVE_CALL_APPROVAL_VALUE" ]; then
    echo "live API calls are disabled by default; set CODEX_ROSETTA_ALLOW_LIVE_CALLS=$LIVE_CALL_APPROVAL_VALUE only after developer approval" >&2
    return 2 2>/dev/null || exit 2
fi
