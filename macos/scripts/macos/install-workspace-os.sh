#!/usr/bin/env bash
set -euo pipefail
source "$(cd "$(dirname "$0")" && pwd)/common.sh"
workspace="${1:-$HOME/Workspace}"; mode="${2:---dry-run}"
args=(init --path "$workspace"); [[ "$mode" == "--apply" ]] || args+=(--dry-run)
run_cli "${args[@]}"

