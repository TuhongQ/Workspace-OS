#!/usr/bin/env bash
set -euo pipefail
source "$(cd "$(dirname "$0")" && pwd)/common.sh"
workspace="${1:-$HOME/Workspace}"; mode="${2:---dry-run}"
args=(scan-inbox --workspace "$workspace" --dry-run); [[ "$mode" == "--apply" ]] && args=(scan-inbox --workspace "$workspace" --apply)
run_cli "${args[@]}"

