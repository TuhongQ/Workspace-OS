"""Build and verify a credential-free portable Workspace OS macOS app ZIP."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import uuid
import zipfile
from datetime import datetime, timezone
from pathlib import Path

from archive_safety import inspect_zip_members, safe_relative_path
from recovery_kit import _collect_source_files, _source_fingerprint


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _zip_info(name: str, executable: bool = False) -> zipfile.ZipInfo:
    info = zipfile.ZipInfo(name)
    info.create_system = 3
    info.external_attr = ((0o100755 if executable else 0o100644) << 16)
    info.compress_type = zipfile.ZIP_DEFLATED
    return info


def generated_files(version: str) -> dict[str, tuple[bytes, bool]]:
    launcher = r'''#!/bin/zsh
set -euo pipefail
APP_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
PAYLOAD="$APP_ROOT/Resources/WorkspaceOS"
PYTHON=""
for candidate in /opt/homebrew/bin/python3 /usr/local/bin/python3 /usr/bin/python3; do
  if [[ -x "$candidate" ]] && "$candidate" -c 'import tkinter' >/dev/null 2>&1; then
    PYTHON="$candidate"
    break
  fi
done
if [[ -z "$PYTHON" ]] && command -v python3 >/dev/null 2>&1 && python3 -c 'import tkinter' >/dev/null 2>&1; then
  PYTHON="$(command -v python3)"
fi
if [[ -z "$PYTHON" ]]; then
  /usr/bin/osascript -e 'display dialog "Workspace OS 需要 Python 3.11+（包含 Tk）。请先安装 python.org 的 macOS Python，然后重新打开。" buttons {"好"} default button "好" with title "Workspace OS 2.0"'
  exit 1
fi
exec "$PYTHON" "$PAYLOAD/scripts/macos/workspace_os_control_center.py"
'''
    info = f'''<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
  <key>CFBundleDisplayName</key><string>Workspace OS</string>
  <key>CFBundleExecutable</key><string>WorkspaceOS</string>
  <key>CFBundleIdentifier</key><string>local.workspaceos.controlcenter</string>
  <key>CFBundleName</key><string>Workspace OS</string>
  <key>CFBundlePackageType</key><string>APPL</string>
  <key>CFBundleShortVersionString</key><string>{version}</string>
  <key>CFBundleVersion</key><string>{version}</string>
  <key>LSMinimumSystemVersion</key><string>12.0</string>
  <key>NSHighResolutionCapable</key><true/>
</dict></plist>
'''
    readme = f'''Workspace OS {version} for macOS

使用方法：
1. 解压 ZIP（不要在 ZIP 内直接运行）。
2. 将“Workspace OS.app”拖入“应用程序”，或直接双击。
3. 首次启动选择本机 Workspace，并在“NAS 设置”填写已挂载路径，例如 /Volumes/Workspace。

功能与 Windows 控制中心一致：初始化、收件箱预览/执行、搜索与索引、快照预览/创建、
健康检查、安全检查、提醒与告警、恢复状态、恢复到新目录、Finder 打开工作区、使用说明，
以及支持本地/NAS 左右比对、上传和下载任务进度的网页版 Workspace OS。

便携版要求 macOS 12+，以及 Python 3.11+（需包含 Tk；建议使用 python.org 官方安装包）。
本 ZIP 在 Windows 上生成并完成结构/哈希/功能测试，未经过 Apple 签名或公证。
首次被 Gatekeeper 阻止时，请在 Finder 中按住 Control 点击应用并选择“打开”。

本安装包不包含用户文件、NAS 数据、账号、密码、Token 或个人设置。
'''
    standalone = r'''#!/bin/zsh
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
PAYLOAD="$HERE/Workspace OS.app/Contents/Resources/WorkspaceOS"
if ! python3 -c 'import PyInstaller' >/dev/null 2>&1; then
  echo "请先安装 PyInstaller：python3 -m pip install pyinstaller"
  exit 2
fi
if [[ -e "$HERE/Standalone/Workspace OS.app" ]]; then
  echo "目标已存在，未覆盖：$HERE/Standalone/Workspace OS.app"
  exit 3
fi
WORK="$(mktemp -d "${TMPDIR:-/tmp}/workspace-os-build.XXXXXX")"
trap 'rm -rf "$WORK"' EXIT
python3 -m PyInstaller --noconfirm --clean --windowed --name "Workspace OS" \
  --distpath "$HERE/Standalone" --workpath "$WORK/build" --specpath "$WORK" \
  --add-data "$PAYLOAD:WorkspaceOS" \
  "$PAYLOAD/scripts/macos/workspace_os_control_center.py"
echo "独立应用已生成：$HERE/Standalone/Workspace OS.app"
echo "如需分发给其他人，请使用你的 Apple Developer ID 完成 codesign 和 notarytool 公证。"
'''
    return {
        "Workspace OS.app/Contents/MacOS/WorkspaceOS": (launcher.encode("utf-8"), True),
        "Workspace OS.app/Contents/Info.plist": (info.encode("utf-8"), False),
        "README-macOS.txt": (readme.encode("utf-8"), False),
        "BUILD-STANDALONE.command": (standalone.encode("utf-8"), True),
    }


def verify(archive: Path) -> dict:
    issues: list[dict[str, str]] = []
    checked = 0
    try:
        with zipfile.ZipFile(archive) as bundle:
            infos = bundle.infolist()
            issues.extend(inspect_zip_members(infos))
            names = {item.filename for item in infos if not item.is_dir()}
            manifests = [name for name in names if name.endswith("MACOS-MANIFEST.json")]
            if len(manifests) != 1:
                issues.append({"code": "MANIFEST_COUNT", "path": str(len(manifests))})
            else:
                manifest_name = manifests[0]
                prefix = manifest_name[: -len("MACOS-MANIFEST.json")]
                manifest = json.loads(bundle.read(manifest_name).decode("utf-8-sig"))
                for item in manifest.get("files", []):
                    relative = str(item.get("path") or "")
                    if not safe_relative_path(relative):
                        issues.append({"code": "UNSAFE_PATH", "path": relative}); continue
                    member = prefix + relative
                    if member not in names:
                        issues.append({"code": "MISSING", "path": relative}); continue
                    payload = bundle.read(member); checked += 1
                    if len(payload) != item.get("size") or hashlib.sha256(payload).hexdigest() != item.get("sha256"):
                        issues.append({"code": "HASH_OR_SIZE_MISMATCH", "path": relative})
                present = {str(item.get("path")) for item in manifest.get("files", [])}
                required = {
                    "Workspace OS.app/Contents/MacOS/WorkspaceOS",
                    "Workspace OS.app/Contents/Info.plist",
                    "Workspace OS.app/Contents/Resources/WorkspaceOS/scripts/macos/workspace_os_control_center.py",
                    "Workspace OS.app/Contents/Resources/WorkspaceOS/scripts/python/workspace_cli.py",
                    "Workspace OS.app/Contents/Resources/WorkspaceOS/scripts/python/dashboard_sync_server.py",
                    "README-macOS.txt", "BUILD-STANDALONE.command",
                }
                for relative in sorted(required - present):
                    issues.append({"code": "REQUIRED_MISSING", "path": relative})
                info_by_name = {item.filename: item for item in infos}
                for relative in ("Workspace OS.app/Contents/MacOS/WorkspaceOS", "BUILD-STANDALONE.command"):
                    member = prefix + relative
                    if member in info_by_name and ((info_by_name[member].external_attr >> 16) & 0o111) == 0:
                        issues.append({"code": "NOT_EXECUTABLE", "path": relative})
    except (OSError, zipfile.BadZipFile, ValueError, json.JSONDecodeError) as exc:
        issues.append({"code": "ARCHIVE_INVALID", "path": str(archive), "detail": type(exc).__name__})
    return {"archive": str(archive), "valid": not issues, "checked_files": checked, "archive_sha256": sha256(archive), "issues": issues}


def build(source: Path, destination: Path) -> dict:
    source_files = _collect_source_files(source)
    fingerprint = _source_fingerprint(source_files)
    version = (source / "VERSION").read_text(encoding="utf-8").strip()
    release = f"WorkspaceOS-{version}-Portable-macOS-{fingerprint[:10]}"
    archive = destination / f"{release}.zip"
    checksum = destination / f"{release}.sha256"
    if archive.exists() or checksum.exists():
        raise FileExistsError(f"macOS package already exists: {archive}")
    generated = generated_files(version)
    destination.mkdir(parents=True, exist_ok=True)
    temporary = destination / f".{release}.{uuid.uuid4().hex}.partial.zip"
    manifest_files: list[dict] = []
    prefix = release + "/"
    try:
        with zipfile.ZipFile(temporary, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as bundle:
            for relative, path in source_files:
                packaged = f"Workspace OS.app/Contents/Resources/WorkspaceOS/{relative}"
                payload = path.read_bytes()
                bundle.writestr(_zip_info(prefix + packaged), payload)
                manifest_files.append({"path": packaged, "size": len(payload), "sha256": hashlib.sha256(payload).hexdigest()})
            for relative, (payload, executable) in generated.items():
                bundle.writestr(_zip_info(prefix + relative, executable), payload)
                manifest_files.append({"path": relative, "size": len(payload), "sha256": hashlib.sha256(payload).hexdigest()})
            manifest = {
                "schema_version": "1.0", "product": "Workspace OS", "platform": "macOS",
                "version": version, "generated_at": datetime.now(timezone.utc).isoformat(),
                "source_fingerprint": fingerprint,
                "requirements": {"macos": "12+", "python": "3.11+ with Tk", "signed": False, "notarized": False},
                "privacy": {"user_data": False, "credentials": False, "settings": False},
                "files": manifest_files,
            }
            manifest_payload = json.dumps(manifest, ensure_ascii=False, indent=2).encode("utf-8")
            bundle.writestr(_zip_info(prefix + "MACOS-MANIFEST.json"), manifest_payload)
        archive_hash = sha256(temporary)
        os.replace(temporary, archive)
        checksum.write_text(f"{archive_hash}  {archive.name}\n", encoding="utf-8")
        verification = verify(archive)
        if not verification["valid"]:
            raise ValueError(f"Post-build verification failed: {verification['issues'][:3]}")
        return {"status": "created", "archive": str(archive), "checksum": str(checksum), "archive_sha256": archive_hash, "archive_bytes": archive.stat().st_size, "verification": verification}
    except Exception:
        temporary.unlink(missing_ok=True)
        raise


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", type=Path)
    parser.add_argument("--destination", type=Path)
    parser.add_argument("--verify", type=Path)
    args = parser.parse_args()
    if args.verify:
        result = verify(args.verify)
    else:
        if not args.source or not args.destination:
            parser.error("--source and --destination are required when building")
        result = build(args.source.resolve(), args.destination.resolve())
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result.get("valid", True) else 2


if __name__ == "__main__":
    raise SystemExit(main())
