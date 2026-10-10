#!/usr/bin/env bash
set -euo pipefail
source "$(cd "$(dirname "$0")" && pwd)/common.sh"
[[ $# -ge 2 ]] || { echo '用法: new-workspace-project.sh TYPE NAME [work|personal] [WORKSPACE] [--apply]' >&2; exit 2; }
kind="$1"; name="$2"; space="${3:-work}"; workspace="${4:-$HOME/Workspace}"; mode="${5:---dry-run}"
args=(new "$kind" "$name" --space "$space" --workspace "$workspace"); [[ "$mode" == "--apply" ]] || args+=(--dry-run)
run_cli "${args[@]}"
