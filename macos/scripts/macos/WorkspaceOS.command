#!/bin/zsh
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
exec /usr/bin/env python3 "$ROOT/scripts/macos/workspace_os_control_center.py"
