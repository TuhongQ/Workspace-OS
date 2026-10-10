"""Build and verify a self-contained, credential-free Workspace OS release."""
from __future__ import annotations

import hashlib
import json
import os
import uuid
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from archive_safety import inspect_zip_members, safe_relative_path
from recovery_kit import _collect_source_files, _source_fingerprint

SCHEMA_VERSION = "1.0"


def _generated_entrypoints(version: str) -> dict[str, bytes]:
    try_cmd = """@echo off
setlocal
cd /d "%~dp0"
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\\windows\\Start-WorkspaceOSTrial.ps1" %*
set "WORKSPACEOS_EXIT=%ERRORLEVEL%"
if not "%WORKSPACEOS_EXIT%"=="0" pause
exit /b %WORKSPACEOS_EXIT%
"""
    open_cmd = """@echo off
setlocal
set "WORKSPACEOS_NEXUS=%LOCALAPPDATA%\\WorkspaceOS-Trial\\Workspace\\08_Indexes\\file-locations.html"
if not exist "%WORKSPACEOS_NEXUS%" (
  echo Trial NEXUS not found. Run TRY-WORKSPACE-OS.cmd first.
  pause
  exit /b 2
)
start "" "%WORKSPACEOS_NEXUS%"
"""
    readme = f"""Workspace OS {version} - Windows first usable release

1. Double-click TRY-WORKSPACE-OS.cmd.
2. The trial writes only to %LOCALAPPDATA%\\WorkspaceOS-Trial.
3. When validation passes, NEXUS opens automatically.
4. Reopen it later with OPEN-TRIAL-NEXUS.cmd.

The trial refuses to write into a non-empty directory without its own marker.
It does not register scheduled tasks or modify an existing Workspace.

Chinese guide: docs\\first-usable-release.md
"""
    return {
        "TRY-WORKSPACE-OS.cmd": try_cmd.encode("utf-8"),
        "OPEN-TRIAL-NEXUS.cmd": open_cmd.encode("utf-8"),
        "README-FIRST.txt": readme.encode("utf-8"),
    }


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def verify_distribution(archive: str | Path) -> dict[str, Any]:
    path = Path(archive).expanduser().resolve()
    issues: list[dict[str, str]] = []
    checked = 0
    if not path.is_file():
        return {
            "schema_version": SCHEMA_VERSION,
            "archive": str(path),
            "valid": False,
            "checked_files": 0,
            "issues": [{"code": "ARCHIVE_MISSING", "path": str(path)}],
        }
    try:
        with zipfile.ZipFile(path) as bundle:
            infos = bundle.infolist()
            issues.extend(inspect_zip_members(infos))
            names = [info.filename for info in infos if not info.filename.endswith("/")]
            manifests = [name for name in names if name.endswith("/DISTRIBUTION-MANIFEST.json")]
            if len(manifests) != 1:
                issues.append({"code": "MANIFEST_COUNT_INVALID", "path": str(path)})
            else:
                manifest_name = manifests[0]
                prefix = manifest_name[: -len("DISTRIBUTION-MANIFEST.json")]
                manifest = json.loads(bundle.read(manifest_name).decode("utf-8-sig"))
                files = manifest.get("files", [])
                expected: set[str] = set()
                for item in files:
                    relative = str(item.get("path") or "")
                    if not safe_relative_path(relative):
                        issues.append({"code": "UNSAFE_MANIFEST_PATH", "path": relative})
                        continue
                    member = prefix + relative
                    expected.add(member)
                    if member not in names:
                        issues.append({"code": "FILE_MISSING", "path": relative})
                        continue
                    payload = bundle.read(member)
                    checked += 1
                    if len(payload) != item.get("size"):
                        issues.append({"code": "SIZE_MISMATCH", "path": relative})
                    elif hashlib.sha256(payload).hexdigest() != item.get("sha256"):
                        issues.append({"code": "HASH_MISMATCH", "path": relative})
                ignored = {manifest_name, prefix + "SHA256SUMS.txt"}
                for unexpected in sorted(set(names) - expected - ignored):
                    issues.append({"code": "UNEXPECTED_FILE", "path": unexpected})
                required = {
                    "TRY-WORKSPACE-OS.cmd",
                    "OPEN-TRIAL-NEXUS.cmd",
                    "README-FIRST.txt",
                    "scripts/python/workspace_cli.py",
                    "scripts/windows/Start-WorkspaceOSTrial.ps1",
                    "scripts/windows/Install-WorkspaceOS.ps1",
                    "README.md",
                    "VERSION",
                }
                present = {str(item.get("path")) for item in files}
                for missing in sorted(required - present):
                    issues.append({"code": "REQUIRED_FILE_MISSING", "path": missing})
                runtime_required = {
                    str(item) for item in manifest.get("runtime_required_files", [])
                    if isinstance(item, str)
                }
                for missing in sorted(runtime_required - present):
                    issues.append({"code": "RUNTIME_REQUIRED_FILE_MISSING", "path": missing})
                privacy = manifest.get("privacy", {})
                if privacy.get("user_data") is not False or privacy.get("credentials") is not False:
                    issues.append({"code": "PRIVACY_DECLARATION_INVALID", "path": manifest_name})
    except (OSError, zipfile.BadZipFile, UnicodeDecodeError, json.JSONDecodeError, KeyError, TypeError) as exc:
        issues.append({"code": "ARCHIVE_INVALID", "path": str(path), "detail": type(exc).__name__})
    return {
        "schema_version": SCHEMA_VERSION,
        "archive": str(path),
        "checked_at": datetime.now(timezone.utc).isoformat(),
        "valid": not issues,
        "checked_files": checked,
        "archive_sha256": _sha256(path),
        "issues": issues,
    }


def build_distribution(
    source: str | Path,
    destination: str | Path,
    *,
    version: str | None = None,
    apply: bool = False,
) -> dict[str, Any]:
    source_root = Path(source).expanduser().resolve()
    destination_root = Path(destination).expanduser().resolve()
    if not (source_root / "scripts" / "python" / "workspace_cli.py").is_file():
        raise ValueError(f"不是有效的 Workspace OS 源码目录: {source_root}")
    detected_version = version or (source_root / "VERSION").read_text(encoding="utf-8").strip()
    source_files = _collect_source_files(source_root)
    fingerprint = _source_fingerprint(source_files)
    generated_files = _generated_entrypoints(detected_version)
    release_name = f"WorkspaceOS-{detected_version}-Windows-{fingerprint[:10]}"
    archive = destination_root / f"{release_name}.zip"
    checksum = destination_root / f"{release_name}.sha256"
    preview = {
        "schema_version": SCHEMA_VERSION,
        "mode": "apply" if apply else "dry-run",
        "status": "planned",
        "source": str(source_root),
        "archive": str(archive),
        "checksum": str(checksum),
        "version": detected_version,
        "source_fingerprint": fingerprint,
        "file_count": len(source_files) + len(generated_files),
        "contains_user_data": False,
        "contains_credentials": False,
        "trial_entrypoint": f"{release_name}/scripts/windows/Start-WorkspaceOSTrial.ps1",
    }
    if not apply:
        return preview
    destination_root.mkdir(parents=True, exist_ok=True)
    if archive.exists() or checksum.exists():
        if archive.is_file() and checksum.is_file():
            verification = verify_distribution(archive)
            expected = checksum.read_text(encoding="utf-8-sig").strip().split()[0].lower()
            if verification["valid"] and expected == verification["archive_sha256"]:
                return {**preview, "status": "existing_verified", "verification": verification}
        raise FileExistsError(f"发行包目标已存在且无法验证，拒绝覆盖: {archive}")

    prefix = f"{release_name}/"
    temporary_archive = destination_root / f".{release_name}.{uuid.uuid4().hex}.partial.zip"
    temporary_checksum = destination_root / f".{release_name}.{uuid.uuid4().hex}.partial.sha256"
    manifest_files: list[dict[str, Any]] = []
    try:
        with zipfile.ZipFile(temporary_archive, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as bundle:
            for relative, path in source_files:
                payload = path.read_bytes()
                bundle.writestr(prefix + relative, payload)
                manifest_files.append({
                    "path": relative,
                    "size": len(payload),
                    "sha256": hashlib.sha256(payload).hexdigest(),
                })
            for relative, payload in generated_files.items():
                bundle.writestr(prefix + relative, payload)
                manifest_files.append({
                    "path": relative,
                    "size": len(payload),
                    "sha256": hashlib.sha256(payload).hexdigest(),
                })
            manifest = {
                "schema_version": SCHEMA_VERSION,
                "generated_at": datetime.now(timezone.utc).isoformat(),
                "product": "Workspace OS",
                "version": detected_version,
                "source_fingerprint": fingerprint,
                "privacy": {"user_data": False, "credentials": False},
                "runtime_required_files": ["config/maintenance-policy.json"],
                "entrypoints": {
                    "double_click_trial": "TRY-WORKSPACE-OS.cmd",
                    "open_trial_nexus": "OPEN-TRIAL-NEXUS.cmd",
                    "trial": "scripts/windows/Start-WorkspaceOSTrial.ps1",
                    "install": "scripts/windows/Install-WorkspaceOS.ps1",
                    "cli": "scripts/python/workspace_cli.py",
                },
                "files": manifest_files,
            }
            bundle.writestr(
                prefix + "DISTRIBUTION-MANIFEST.json",
                json.dumps(manifest, ensure_ascii=False, indent=2).encode("utf-8"),
            )
            sums = "\n".join(f"{item['sha256']}  {item['path']}" for item in manifest_files) + "\n"
            bundle.writestr(prefix + "SHA256SUMS.txt", sums.encode("utf-8"))
        if _source_fingerprint(_collect_source_files(source_root)) != fingerprint:
            raise OSError(
                "SOURCE_CHANGED_DURING_EXPORT: distribution source changed "
                "between inventory and archive completion"
            )
        archive_hash = _sha256(temporary_archive)
        temporary_checksum.write_text(f"{archive_hash}  {archive.name}\n", encoding="utf-8")
        os.replace(temporary_archive, archive)
        os.replace(temporary_checksum, checksum)
        verification = verify_distribution(archive)
        if not verification["valid"] or verification["archive_sha256"] != archive_hash:
            raise ValueError("发行包提交后校验失败")
    except Exception:
        for temporary in (temporary_archive, temporary_checksum):
            try:
                temporary.unlink()
            except OSError:
                pass
        raise
    return {
        **preview,
        "status": "created",
        "archive_sha256": archive_hash,
        "archive_bytes": archive.stat().st_size,
        "verification": verification,
    }
