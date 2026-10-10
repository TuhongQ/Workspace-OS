#!/usr/bin/env bash
set -euo pipefail
source "$(cd "$(dirname "$0")" && pwd)/common.sh"

[[ $# -ge 4 && $# -le 6 ]] || {
  echo "用法：$0 SOURCE_WORKSPACE TARGET_WORKSPACE SOURCE_MANIFEST TARGET_MANIFEST [OUTPUT] [--apply]" >&2
  exit 2
}

source_workspace=$1
target_workspace=$2
source_manifest=$3
target_manifest=$4
output="$target_workspace/08_Indexes/Devices/device-apply-status.json"
mode=
if [[ $# -ge 5 ]]; then
  if [[ "$5" == "--apply" ]]; then
    mode=--apply
  else
    output=$5
  fi
fi
[[ $# -eq 6 ]] && mode=$6
args=(
  device-apply
  --source-workspace "$source_workspace"
  --target-workspace "$target_workspace"
  --source-manifest "$source_manifest"
  --target-manifest "$target_manifest"
  --output "$output"
)
[[ "$mode" == "--apply" ]] && args+=(--apply)
run_cli "${args[@]}"
