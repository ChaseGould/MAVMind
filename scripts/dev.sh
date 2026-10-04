#!/usr/bin/env bash
# Start the vehicle and agent services for development. Usage: scripts/dev.sh [profile]
set -euo pipefail
cd "$(dirname "$0")/.."
PROFILE="${1:-replay}"
python -m mavmind_vehicle --profile "$PROFILE" &
VEHICLE=$!
trap 'kill $VEHICLE 2>/dev/null' EXIT
sleep 2
python -m mavmind_agent
