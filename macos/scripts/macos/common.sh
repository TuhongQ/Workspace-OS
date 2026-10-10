#!/usr/bin/env bash
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CLI="$SCRIPT_DIR/../python/workspace_cli.py"
command -v python3 >/dev/null 2>&1 || { echo '错误：需要 Python 3.11+' >&2; exit 2; }
python3 -c 'import sys; raise SystemExit(sys.version_info < (3, 11))' || { echo '错误：需要 Python 3.11+' >&2; exit 2; }
run_cli() { python3 "$CLI" "$@"; }
