#!/bin/zsh
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
DESTINATION="${1:-$ROOT/dist-macos}"
if ! python3 -c 'import PyInstaller' >/dev/null 2>&1; then
  echo "请先安装 PyInstaller：python3 -m pip install pyinstaller"
  exit 2
fi
if [[ -e "$DESTINATION/Workspace OS.app" ]]; then
  echo "目标已存在，未覆盖：$DESTINATION/Workspace OS.app"
  exit 3
fi
WORK="$(mktemp -d "${TMPDIR:-/tmp}/workspace-os-build.XXXXXX")"
trap 'rm -rf "$WORK"' EXIT
python3 -m PyInstaller --noconfirm --clean --windowed --name "Workspace OS" \
  --distpath "$DESTINATION" --workpath "$WORK/build" --specpath "$WORK" \
  --add-data "$ROOT:WorkspaceOS" \
  "$ROOT/scripts/macos/workspace_os_control_center.py"
echo "已生成：$DESTINATION/Workspace OS.app"
