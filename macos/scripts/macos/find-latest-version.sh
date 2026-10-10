#!/usr/bin/env bash
set -euo pipefail
source "$(cd "$(dirname "$0")" && pwd)/common.sh"
[[ $# -eq 1 ]] || { echo '用法: find-latest-version.sh PATH' >&2; exit 2; }; run_cli latest "$1"

