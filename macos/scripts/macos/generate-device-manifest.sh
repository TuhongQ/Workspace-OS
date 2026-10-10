#!/usr/bin/env bash
set -euo pipefail
source "$(cd "$(dirname "$0")" && pwd)/common.sh"

workspace="${1:-$HOME/Workspace}"
device_id="${2:-$(hostname -s)}"
output="${3:-$workspace/08_Indexes/Devices/local-device-manifest.json}"

run_cli device-manifest \
  --workspace "$workspace" \
  --device-id "$device_id" \
  --output "$output"
