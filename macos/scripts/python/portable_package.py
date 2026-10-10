"""Build and verify a credential-free, Python-included portable Workspace OS ZIP."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import uuid
import zipfile
from datetime import datetime, timezone
from pathlib import Path

from archive_safety import inspect_zip_members, safe_relative_path
from recovery_kit import _collect_source_files, _source_fingerprint

RUNTIME_FILES = {
    "python.exe", "pythonw.exe", "python3.dll", "python311.dll",
    "vcruntime140.dll", "vcruntime140_1.dll", "LICENSE.txt",
}
RUNTIME_DIRS = {"DLLs", "Lib"}
RUNTIME_EXCLUDED_PARTS = {"site-packages", "__pycache__", "test", "tests", "idlelib", "turtledemo"}
RUNTIME_EXCLUDED_SUFFIXES = {".pyc", ".pyo"}


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def runtime_files(root: Path) -> list[tuple[str, Path]]:
    records: list[tuple[str, Path]] = []
    for name in sorted(RUNTIME_FILES):
        path = root / name
        if not path.is_file():
            raise ValueError(f"Python runtime file missing: {path}")
        records.append((f"runtime/python/{name}", path))
    for name in sorted(RUNTIME_DIRS):
        directory = root / name
        if not directory.is_dir():
            raise ValueError(f"Python runtime directory missing: {directory}")
        for path in sorted(directory.rglob("*")):
            if not path.is_file():
                continue
            relative = path.relative_to(root)
            if any(part.lower() in RUNTIME_EXCLUDED_PARTS for part in relative.parts):
                continue
            if path.suffix.lower() in RUNTIME_EXCLUDED_SUFFIXES:
                continue
            records.append((f"runtime/python/{relative.as_posix()}", path))
    return records


def generated_files(version: str) -> dict[str, bytes]:
    launcher = r'''@echo off
setlocal
cd /d "%~dp0"
powershell.exe -NoProfile -ExecutionPolicy Bypass -STA -File "%~dp0scripts\windows\WorkspaceOS-ControlCenter-WPF.ps1"
set "WORKSPACEOS_EXIT=%ERRORLEVEL%"
if not "%WORKSPACEOS_EXIT%"=="0" pause
exit /b %WORKSPACEOS_EXIT%
'''
    install = r'''@echo off
setlocal
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\windows\Install-PortableWorkspaceOS.ps1" -PackageRoot "%~dp0"
if errorlevel 1 pause
'''
    installer = r'''param([Parameter(Mandatory)][string]$PackageRoot)
$ErrorActionPreference='Stop'
$root=[IO.Path]::GetFullPath($PackageRoot)
$launcher=Join-Path $root 'WorkspaceOS.cmd'
if(-not(Test-Path -LiteralPath $launcher)){throw "Launcher not found: $launcher"}
$desktop=[Environment]::GetFolderPath('Desktop')
$shortcut=Join-Path $desktop 'Workspace OS 2.0.lnk'
$shell=New-Object -ComObject WScript.Shell
$link=$shell.CreateShortcut($shortcut)
$link.TargetPath=$launcher
$link.WorkingDirectory=$root
$link.IconLocation="$env:SystemRoot\System32\shell32.dll,137"
$link.Description='Workspace OS 2.0 portable control center'
$link.Save()
[System.Windows.MessageBox]::Show("Desktop shortcut created:`n$shortcut",'Workspace OS 2.0','OK','Information') | Out-Null
'''
    readme = f"""Workspace OS {version} Portable for Windows

1. Extract this ZIP to a normal local folder. Do not run it from inside the ZIP.
2. Double-click WorkspaceOS.cmd.
3. Choose your Workspace folder on first use.
4. Optional: run INSTALL-WORKSPACE-OS.cmd to create a desktop shortcut.

After opening the control center on a new computer, click "NAS 设置" and enter
the NAS share path (for example: \\\\192.168.100.110\Workspace). The setting is
saved only in that Windows user's profile.

This package includes a private Python runtime. It does not contain user files,
credentials, passwords, tokens, snapshots, or NAS data.
"""
    return {
        "WorkspaceOS.cmd": launcher.encode("utf-8"),
        "INSTALL-WORKSPACE-OS.cmd": install.encode("utf-8"),
        "scripts/windows/Install-PortableWorkspaceOS.ps1": installer.encode("utf-8"),
        "README-PORTABLE.txt": readme.encode("utf-8"),
    }


def verify(archive: Path) -> dict:
    issues: list[dict[str, str]] = []
    checked = 0
    try:
        with zipfile.ZipFile(archive) as bundle:
            infos = bundle.infolist()
            issues.extend(inspect_zip_members(infos))
            names = {item.filename for item in infos if not item.is_dir()}
            manifests = [name for name in names if name.endswith("PORTABLE-MANIFEST.json")]
            if len(manifests) != 1:
                issues.append({"code": "MANIFEST_COUNT", "path": str(len(manifests))})
            else:
                manifest_name = manifests[0]
                prefix = manifest_name[: -len("PORTABLE-MANIFEST.json")]
                manifest = json.loads(bundle.read(manifest_name).decode("utf-8-sig"))
                privacy = manifest.get("privacy")
                if not isinstance(privacy, dict) or privacy.get("user_data") is not False or privacy.get("credentials") is not False:
                    issues.append({"code": "PRIVACY_DECLARATION_INVALID", "path": manifest_name})
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
                for required in {"WorkspaceOS.cmd", "runtime/python/python.exe", "scripts/windows/WorkspaceOS-ControlCenter-WPF.ps1", "scripts/python/workspace_cli.py"}:
                    if required not in present:
                        issues.append({"code": "REQUIRED_MISSING", "path": required})
    except (OSError, zipfile.BadZipFile, ValueError, json.JSONDecodeError) as exc:
        issues.append({"code": "ARCHIVE_INVALID", "path": str(archive), "detail": type(exc).__name__})
    return {"archive": str(archive), "valid": not issues, "checked_files": checked, "archive_sha256": sha256(archive), "issues": issues}


def build(source: Path, runtime: Path, destination: Path) -> dict:
    source_files = _collect_source_files(source)
    fingerprint = _source_fingerprint(source_files)
    version = (source / "VERSION").read_text(encoding="utf-8").strip()
    release = f"WorkspaceOS-{version}-Portable-Windows-{fingerprint[:10]}"
    archive = destination / f"{release}.zip"
    checksum = destination / f"{release}.sha256"
    if archive.exists() or checksum.exists():
        raise FileExistsError(f"Portable target already exists: {archive}")
    records = source_files + runtime_files(runtime)
    generated = generated_files(version)
    destination.mkdir(parents=True, exist_ok=True)
    temporary = destination / f".{release}.{uuid.uuid4().hex}.partial.zip"
    manifest_files: list[dict] = []
    try:
        with zipfile.ZipFile(temporary, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as bundle:
            prefix = f"{release}/"
            for relative, path in records:
                payload = path.read_bytes()
                bundle.writestr(prefix + relative, payload)
                manifest_files.append({"path": relative, "size": len(payload), "sha256": hashlib.sha256(payload).hexdigest()})
            for relative, payload in generated.items():
                bundle.writestr(prefix + relative, payload)
                manifest_files.append({"path": relative, "size": len(payload), "sha256": hashlib.sha256(payload).hexdigest()})
            manifest = {"schema_version": "1.0", "product": "Workspace OS", "version": version, "generated_at": datetime.now(timezone.utc).isoformat(), "source_fingerprint": fingerprint, "runtime": {"python": "3.11", "bundled": True}, "privacy": {"user_data": False, "credentials": False}, "files": manifest_files}
            bundle.writestr(prefix + "PORTABLE-MANIFEST.json", json.dumps(manifest, ensure_ascii=False, indent=2).encode("utf-8"))
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
    parser.add_argument("--runtime", type=Path)
    parser.add_argument("--destination", type=Path)
    parser.add_argument("--verify", type=Path)
    args = parser.parse_args()
    if args.verify:
        result = verify(args.verify)
    else:
        if not args.source or not args.runtime or not args.destination:
            parser.error("--source, --runtime and --destination are required when building")
        result = build(args.source.resolve(), args.runtime.resolve(), args.destination.resolve())
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result.get("valid", True) else 2


if __name__ == "__main__":
    raise SystemExit(main())
