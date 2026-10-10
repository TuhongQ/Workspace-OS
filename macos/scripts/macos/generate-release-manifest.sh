#!/usr/bin/env bash
set -euo pipefail
source "$(cd "$(dirname "$0")" && pwd)/common.sh"
[[ $# -ge 1 ]] || { echo '用法: generate-release-manifest.sh PATH [VERSION] [--apply]' >&2; exit 2; }
[[ "${3:---dry-run}" == "--apply" ]] || { echo "预览：将为 $1 生成发布清单"; exit 0; }
run_cli manifest "$1" --release-version "${2:-unknown}"

