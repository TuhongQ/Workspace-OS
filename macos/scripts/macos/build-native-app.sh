#!/bin/zsh
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
DESTINATION="${1:?Specify a fresh build output directory}"
[[ ! -e "$DESTINATION" ]] || { echo "构建目录已存在，未覆盖"; exit 2; }
PYTHON="${WORKSPACE_BUILD_PYTHON:-/opt/homebrew/opt/pyinstaller/libexec/bin/python}"
DESTINATION="$("$PYTHON" -c 'import os,sys; print(os.path.realpath(sys.argv[1]))' "$DESTINATION")"
case "$DESTINATION/" in "$ROOT/"*) echo "构建目录不能位于源码目录内"; exit 2;; esac
"$PYTHON" -c 'import sys, PyInstaller; assert sys.version_info >= (3, 11)'
mkdir -p "$DESTINATION"
WORK="$(mktemp -d "${TMPDIR:-/tmp}/workspace-native.XXXXXX")"
APP="$DESTINATION/Workspace OS.app"
mkdir -p "$APP/Contents/MacOS" "$APP/Contents/Resources"
"$PYTHON" -m PyInstaller --noconfirm --clean --onefile --console --name WorkspaceOSHelper \
  --distpath "$WORK/dist" --workpath "$WORK/build" --specpath "$WORK/spec" \
  --paths "$ROOT/scripts/python" --hidden-import workspace_cli \
  --hidden-import dashboard_sync_server --hidden-import mac_app_backend \
  "$ROOT/scripts/macos/workspace_os_helper.py"
swiftc "$ROOT/scripts/macos/WorkspaceApp.swift" -O -target arm64-apple-macos13.0 \
  -o "$APP/Contents/MacOS/WorkspaceOS" -framework AppKit -framework WebKit
"$PYTHON" -m PyInstaller --noconfirm --clean --onefile --console --name WorkspaceOSMaintenance \
  --distpath "$WORK/maintenance-dist" --workpath "$WORK/maintenance-build" --specpath "$WORK/maintenance-spec" \
  "$ROOT/scripts/macos/workspace_os_control_center.py"
install -m 755 "$WORK/maintenance-dist/WorkspaceOSMaintenance" "$APP/Contents/MacOS/WorkspaceOSMaintenance"
install -m 755 "$WORK/dist/WorkspaceOSHelper" "$APP/Contents/MacOS/WorkspaceOSHelper"
"$PYTHON" "$ROOT/scripts/macos/stage-release-source.py" "$ROOT" "$APP/Contents/Resources/WorkspaceOS"
cp "$ROOT/scripts/macos/NativeInfo.plist" "$APP/Contents/Info.plist"
ICONSET="$WORK/WorkspaceOS.iconset"
mkdir -p "$ICONSET"
for size in 16 32 128 256 512; do
  sips -z "$size" "$size" "$ROOT/assets/workspace-icon.png" --out "$ICONSET/icon_${size}x${size}.png" >/dev/null
  double=$((size * 2))
  sips -z "$double" "$double" "$ROOT/assets/workspace-icon.png" --out "$ICONSET/icon_${size}x${size}@2x.png" >/dev/null
done
iconutil -c icns "$ICONSET" -o "$APP/Contents/Resources/WorkspaceOS.icns"
/usr/bin/codesign --force --deep --sign - "$APP"
echo "已生成：$APP"
echo "构建临时文件保留于：$WORK"
