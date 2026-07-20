#!/bin/bash
# Launch Codex CLI through Rosetta Gateway
# Usage: ./scripts/rosetta-test-codex.sh [profile]
#   profile: rosetta-openai (default), rosetta-anthropic, rosetta-google
#   Profiles are defined in ~/.codex/config.toml

set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
# shellcheck source=scripts/require_live_call_approval.sh
. "$SCRIPT_DIR/require_live_call_approval.sh"

PROFILE="${1:-rosetta-openai}"

exec codex --profile "$PROFILE"
