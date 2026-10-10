#!/usr/bin/env bash
set -euo pipefail
source "$(cd "$(dirname "$0")" && pwd)/common.sh"

computer_path="${1:-$HOME/Workspace}"
nas_path="${2:-/Volumes/Workspace}"
local_output="${3:-$computer_path/08_Indexes/file-locations.html}"
nas_output="$nas_path/08_Indexes/file-locations.html"

[[ -d "$computer_path" ]] || { echo "错误：Mac 工作区不存在：$computer_path" >&2; exit 2; }
[[ -d "$nas_path" ]] || { echo "错误：NAS 尚未挂载：$nas_path" >&2; exit 2; }

python3 -c 'import sys; from pathlib import Path; sys.path.insert(0, sys.argv[1]); from dashboard_sync_server import SyncJobs; result = SyncJobs(Path(sys.argv[2]), Path(sys.argv[3]), Path(sys.argv[4])).refresh_snapshot(live_nas=True); print(result); raise SystemExit(1 if result.get("publish_error") else 0)' \
  "$SCRIPT_DIR/../python" "$computer_path" "$nas_path" "$local_output"
open "$nas_output"
