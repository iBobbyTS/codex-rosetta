#!/bin/bash
# Launch OpenCode through Rosetta Gateway
# Usage: ./scripts/rosetta-test-opencode.sh [model]
#   model defaults to gpt-4.1-nano
#   Available models: gpt-4.1-nano, anthropic/claude-haiku-4.5, gemini-2.5-flash-lite
#   Models are defined in ~/.config/opencode/opencode.json under "rosetta" provider

set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
# shellcheck source=scripts/require_live_call_approval.sh
. "$SCRIPT_DIR/require_live_call_approval.sh"

MODEL="${1:-gpt-4.1-nano}"

exec opencode -m "rosetta/$MODEL"
