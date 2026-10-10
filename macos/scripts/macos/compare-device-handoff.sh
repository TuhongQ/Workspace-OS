#!/usr/bin/env bash
set -euo pipefail
source "$(cd "$(dirname "$0")" && pwd)/common.sh"

[[ $# -eq 3 ]] || {
  echo "用法：$0 SOURCE_MANIFEST TARGET_MANIFEST OUTPUT" >&2
  exit 2
}
run_cli device-compare "$1" "$2" --output "$3"
