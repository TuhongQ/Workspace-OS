"""Build and verify a portable, credential-free Workspace OS recovery kit."""
from __future__ import annotations

import hashlib
import json
import os
import re
import uuid
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from archive_safety import inspect_zip_members, safe_relative_path
from path_safety import find_link_entries, is_link_or_reparse, iter_files_no_links
ROOT_FILES = {
    "AGENTS.md", "CHANGELOG.md", "LICENSE", "README.md", "VERSION",
}
SOURCE_DIRS = {
    "config", "docs", "examples", "migration", "nas", "obsidian", "scripts", "search",
    "shortcuts", "templates", "tests", "workspace-sample",
}
EXCLUDED_PARTS = {
    ".codex", ".git", ".pytest_cache", ".venv", ".vs", "__pycache__",
    "node_modules", "workspace-test",
}
EXCLUDED_SUFFIXES = {".pyc", ".pyo"}
PUBLIC_CONFIG_FILES = {"maintenance-policy.json"}
RECOVERY_ARCHIVE_PATTERN = re.compile(
    r"^WorkspaceOS-Recovery-(?P<flavor>Kit|Portable)-.+\.zip$",
    re.IGNORECASE,
)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _safe_config_file(path: Path) -> bool:
    name = path.name.lower()
    return (
        ".example." in name
        or name.startswith("example.")
        or name.endswith(".example")
        or name in PUBLIC_CONFIG_FILES
    )


def _validate_retention_root(path: Path) -> None:
    anchor = Path(path.anchor) if path.anchor else None
    if not path.name or (anchor and path == anchor):
        raise ValueError(f"恢复包保留目标不能是文件系统根目录: {path}")


def _bucket_keys(moment: datetime) -> dict[str, str]:
    iso_year, iso_week, _ = moment.isocalendar()
    return {
        "daily": moment.strftime("%Y-%m-%d"),
        "weekly": f"{iso_year}-W{iso_week:02d}",
        "monthly": moment.strftime("%Y-%m"),
    }


def apply_recovery_kit_retention(
    destination: str | Path,
    *,
    keep_latest: int = 3,
    daily: int = 7,
    weekly: int = 8,
    monthly: int = 6,
    protect_reports: list[str | Path] | None = None,
    apply: bool = False,
) -> dict[str, Any]:
    """Preview or move superseded recovery-kit pairs to recoverable trash."""
    root = Path(destination).expanduser().resolve()
    _validate_retention_root(root)
    for label, value in {
        "keep_latest": keep_latest,
        "daily": daily,
        "weekly": weekly,
        "monthly": monthly,
    }.items():
        if value < 0:
            raise ValueError(f"{label} 不能为负数")
    if keep_latest < 1:
        raise ValueError("keep_latest 至少为 1，避免淘汰每种恢复包的最新版本")

    protected_archives: set[Path] = set()
    report_issues: list[dict[str, str]] = []
    for report_value in protect_reports or []:
        report_path = Path(report_value).expanduser().resolve()
        try:
            report = json.loads(report_path.read_text(encoding="utf-8-sig"))
            archive_value = report.get("archive")
            if not isinstance(archive_value, str):
                raise ValueError("missing archive field")
            archive_path = Path(archive_value).expanduser().resolve()
            if archive_path.parent != root:
                raise ValueError("archive is outside retention root")
            protected_archives.add(archive_path)
        except (OSError, ValueError, TypeError, json.JSONDecodeError) as exc:
            report_issues.append({"report": str(report_path), "error": str(exc)})

    records: list[dict[str, Any]] = []
    orphans: list[dict[str, str]] = []
    if root.is_dir():
        for archive in root.iterdir():
            if not archive.is_file():
                continue
            match = RECOVERY_ARCHIVE_PATTERN.match(archive.name)
            if not match:
                continue
            checksum = archive.with_suffix(".sha256")
            pin = archive.with_suffix(".keep")
            if not checksum.is_file():
                orphans.append({
                    "archive": str(archive),
                    "reason": "checksum_missing",
                })
                continue
            stat = archive.stat()
            moment = datetime.fromtimestamp(stat.st_mtime, timezone.utc)
            records.append({
                "archive": archive,
                "checksum": checksum,
                "flavor": match.group("flavor").lower(),
                "modified_at": moment,
                "bytes": stat.st_size + checksum.stat().st_size,
                "pinned": pin.is_file(),
                "report_protected": archive in protected_archives,
            })

    keep_paths: set[Path] = set()
    keep_reasons: dict[Path, set[str]] = {}

    def keep(record: dict[str, Any], reason: str) -> None:
        archive = record["archive"]
        keep_paths.add(archive)
        keep_reasons.setdefault(archive, set()).add(reason)

    for flavor in ("kit", "portable"):
        items = sorted(
            (record for record in records if record["flavor"] == flavor),
            key=lambda record: (record["modified_at"], record["archive"].name),
            reverse=True,
        )
        for record in items[:keep_latest]:
            keep(record, "latest")
        for record in items:
            if record["pinned"]:
                keep(record, "pinned")
            if record["report_protected"]:
                keep(record, "report")
        for period, limit in (("daily", daily), ("weekly", weekly), ("monthly", monthly)):
            seen: set[str] = set()
            for record in items:
                key = _bucket_keys(record["modified_at"])[period]
                if key in seen:
                    continue
                if len(seen) >= limit:
                    break
                seen.add(key)
                keep(record, period)

    kept = [
        {
            "archive": str(record["archive"]),
            "checksum": str(record["checksum"]),
            "flavor": record["flavor"],
            "modified_at": record["modified_at"].isoformat(),
            "bytes": record["bytes"],
            "reasons": sorted(keep_reasons.get(record["archive"], {"policy"})),
        }
        for record in records
        if record["archive"] in keep_paths
    ]
    expired = [
        {
            "archive": str(record["archive"]),
            "checksum": str(record["checksum"]),
            "flavor": record["flavor"],
            "modified_at": record["modified_at"].isoformat(),
            "bytes": record["bytes"],
        }
        for record in records
        if record["archive"] not in keep_paths
    ]
    result: dict[str, Any] = {
        "schema_version": "1.0",
        "mode": "apply" if apply else "dry-run",
        "status": "planned",
        "destination": str(root),
        "policy": {
            "keep_latest": keep_latest,
            "daily": daily,
            "weekly": weekly,
            "monthly": monthly,
        },
        "keep": sorted(kept, key=lambda item: item["archive"]),
        "move_to_trash": sorted(expired, key=lambda item: item["archive"]),
        "orphans": sorted(orphans, key=lambda item: item["archive"]),
        "report_issues": report_issues,
        "reclaimable_bytes": sum(item["bytes"] for item in expired),
    }
    if not apply or not expired:
        if apply:
            result["status"] = "nothing_to_move"
            result["moved"] = []
        return result

    batch = root / "_WorkspaceOS_Trash" / "RecoveryKits" / (
        datetime.now().strftime("%Y%m%d-%H%M%S") + "-" + uuid.uuid4().hex[:8]
    )
    batch.mkdir(parents=True, exist_ok=False)
    moved: list[dict[str, str]] = []
    for item in expired:
        archive = Path(item["archive"])
        checksum = Path(item["checksum"])
        final = batch / archive.stem
        staging = batch / f".{archive.stem}.{uuid.uuid4().hex}.partial"
        staging.mkdir()
        moved_archive = staging / archive.name
        moved_checksum = staging / checksum.name
        try:
            archive.replace(moved_archive)
            checksum.replace(moved_checksum)
            staging.replace(final)
        except Exception:
            if moved_checksum.exists() and not checksum.exists():
                moved_checksum.replace(checksum)
            if moved_archive.exists() and not archive.exists():
                moved_archive.replace(archive)
            raise
        moved.append({
            "archive": str(archive),
            "checksum": str(checksum),
            "trash": str(final),
        })
    result.update(status="applied", trash=str(batch), moved=moved)
    return result


def _collect_source_files(source: Path) -> list[tuple[str, Path]]:
    records: list[tuple[str, Path]] = []
    for name in sorted(ROOT_FILES):
        path = source / name
        if is_link_or_reparse(path):
            raise ValueError(f"UNSAFE_EXPORT_SOURCE_LINK: {name}")
        if path.is_file():
            records.append((name, path))
    for directory in sorted(SOURCE_DIRS):
        root = source / directory
        if is_link_or_reparse(root):
            raise ValueError(f"UNSAFE_EXPORT_SOURCE_LINK: {directory}")
        if not root.is_dir():
            continue
        unsafe = find_link_entries(root)
        if unsafe:
            relative = unsafe[0].relative_to(source).as_posix()
            raise ValueError(f"UNSAFE_EXPORT_SOURCE_LINK: {relative}")
        for path in iter_files_no_links(root):
            relative = path.relative_to(source)
            if any(part.lower() in EXCLUDED_PARTS for part in relative.parts):
                continue
            if path.suffix.lower() in EXCLUDED_SUFFIXES:
                continue
            if relative.parts[0] == "config" and not _safe_config_file(path):
                continue
            records.append((relative.as_posix(), path))
    return sorted(records)


def _source_fingerprint(files: list[tuple[str, Path]]) -> str:
    digest = hashlib.sha256()
    for relative, path in files:
        digest.update(relative.encode("utf-8"))
        digest.update(b"\0")
        digest.update(_sha256(path).encode("ascii"))
        digest.update(b"\n")
    return digest.hexdigest()


def _restore_instructions(version: str, generated_at: str) -> str:
    return f"""# Workspace OS {version} 恢复工具包

生成时间：{generated_at}

此工具包不包含 Workspace 用户文件、密码、Token、私钥或 restic 仓库密码。

## 首次恢复

1. 在隔离目录解压，不要覆盖现有 Workspace 或程序目录。
2. 验证外层 `.sha256`，再运行：
   - Windows：`python scripts/python/workspace_cli.py recovery-kit-verify <本 zip 路径>`
   - macOS/Linux：`python3 scripts/python/workspace_cli.py recovery-kit-verify <本 zip 路径>`
3. 阅读 `docs/disaster-recovery.md` 和 `docs/backup-and-recovery.md`。
4. 先校验快照，再恢复到全新目录；不要原地覆盖。
5. restic 仓库密码必须从独立离线介质取得，工具包不会保存它。

## 边界

- `tools/windows/restic.exe` 如存在，仅是可公开校验的程序二进制，不含仓库或凭据。
- 示例配置可以复制后编辑；不要把真实密钥写回程序仓库。
- `RECOVERY-KIT-MANIFEST.json` 记录每个文件的大小与 SHA-256。
"""


def verify_recovery_kit(archive: str | Path) -> dict[str, Any]:
    path = Path(archive).expanduser().resolve()
    if not path.is_file():
        raise ValueError(f"恢复工具包不存在: {path}")
    issues: list[dict[str, Any]] = []
    with zipfile.ZipFile(path, "r") as bundle:
        infos = bundle.infolist()
        names = [info.filename for info in infos]
        issues.extend(inspect_zip_members(infos))
        manifest_names = [name for name in names if name.endswith("/RECOVERY-KIT-MANIFEST.json")]
        if len(manifest_names) != 1:
            issues.append({"code": "MANIFEST_COUNT", "path": str(len(manifest_names))})
            manifest = None
        else:
            try:
                manifest = json.loads(bundle.read(manifest_names[0]).decode("utf-8"))
            except (KeyError, UnicodeDecodeError, json.JSONDecodeError):
                manifest = None
                issues.append({"code": "MANIFEST_INVALID", "path": manifest_names[0]})
        checked = 0
        if manifest:
            prefix = manifest_names[0].removesuffix("RECOVERY-KIT-MANIFEST.json")
            expected = set()
            for item in manifest.get("files", []):
                relative = item.get("path", "")
                if not safe_relative_path(relative):
                    issues.append({"code": "UNSAFE_MANIFEST_PATH", "path": str(relative)})
                    continue
                internal = prefix + relative
                expected.add(internal)
                try:
                    payload = bundle.read(internal)
                except KeyError:
                    issues.append({"code": "MISSING_FILE", "path": relative})
                    continue
                checked += 1
                if len(payload) != item.get("size"):
                    issues.append({"code": "SIZE_MISMATCH", "path": relative})
                elif hashlib.sha256(payload).hexdigest() != item.get("sha256"):
                    issues.append({"code": "HASH_MISMATCH", "path": relative})
            ignored = {manifest_names[0], prefix + "SHA256SUMS.txt"}
            unexpected = sorted(set(names) - expected - ignored)
            for name in unexpected:
                if not name.endswith("/"):
                    issues.append({"code": "UNEXPECTED_FILE", "path": name})
            runtime_required = {
                str(item) for item in manifest.get("runtime_required_files", [])
                if isinstance(item, str)
            }
            present = {name.removeprefix(prefix) for name in expected}
            for missing in sorted(runtime_required - present):
                issues.append({"code": "RUNTIME_REQUIRED_FILE_MISSING", "path": missing})
    return {
        "schema_version": "1.0",
        "archive": str(path),
        "checked_at": datetime.now(timezone.utc).isoformat(),
        "valid": not issues,
        "checked_files": checked,
        "archive_sha256": _sha256(path),
        "issues": issues,
    }


def build_recovery_kit(
    source: str | Path,
    destination: str | Path,
    *,
    version: str | None = None,
    name: str | None = None,
    restic_executable: str | Path | None = None,
    apply: bool = False,
) -> dict[str, Any]:
    source_root = Path(source).expanduser().resolve()
    destination_root = Path(destination).expanduser().resolve()
    if not (source_root / "scripts" / "python" / "workspace_cli.py").is_file():
        raise ValueError(f"不是有效的 Workspace OS 源码目录: {source_root}")
    detected_version = version or (source_root / "VERSION").read_text(encoding="utf-8").strip()
    source_files = _collect_source_files(source_root)
    restic_path = Path(restic_executable).expanduser().resolve() if restic_executable else None
    if restic_path and is_link_or_reparse(restic_path):
        raise ValueError("UNSAFE_EXPORT_SOURCE_LINK: tools/windows/restic.exe")
    if restic_path and restic_path.is_file():
        source_files.append(("tools/windows/restic.exe", restic_path))
    source_fingerprint = _source_fingerprint(source_files)
    flavor = "Kit" if restic_path and restic_path.is_file() else "Portable"
    kit_name = name or (
        f"WorkspaceOS-Recovery-{flavor}-{detected_version}-"
        f"{datetime.now().strftime('%Y%m%d')}-{source_fingerprint[:10]}"
    )
    if not kit_name or any(char in kit_name for char in '<>:"/\\|?*'):
        raise ValueError("恢复工具包名称为空或包含非法字符")
    archive = destination_root / f"{kit_name}.zip"
    checksum = destination_root / f"{kit_name}.sha256"
    preview = {
        "schema_version": "1.0",
        "mode": "apply" if apply else "dry-run",
        "status": "planned",
        "source": str(source_root),
        "archive": str(archive),
        "checksum": str(checksum),
        "version": detected_version,
        "source_fingerprint": source_fingerprint,
        "file_count": len(source_files) + 1,
        "includes_restic": bool(restic_path and restic_path.is_file()),
        "contains_user_data": False,
        "contains_credentials": False,
    }
    if not apply:
        return preview
    destination_root.mkdir(parents=True, exist_ok=True)
    if archive.exists() or checksum.exists():
        if archive.is_file() and checksum.is_file():
            verification = verify_recovery_kit(archive)
            expected_line = checksum.read_text(encoding="utf-8-sig").strip().split()[0].lower()
            if verification["valid"] and expected_line == verification["archive_sha256"]:
                return {**preview, "status": "existing_verified", "verification": verification}
        raise FileExistsError(f"恢复工具包目标已存在且无法验证，拒绝覆盖: {archive}")

    generated_at = datetime.now(timezone.utc).isoformat()
    prefix = f"{kit_name}/"
    temp_archive = destination_root / f".{kit_name}.{uuid.uuid4().hex}.partial.zip"
    temp_checksum = destination_root / f".{kit_name}.{uuid.uuid4().hex}.partial.sha256"
    manifest_files: list[dict[str, Any]] = []
    try:
        with zipfile.ZipFile(temp_archive, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as bundle:
            for relative, path in source_files:
                payload = path.read_bytes()
                bundle.writestr(prefix + relative, payload)
                manifest_files.append({
                    "path": relative,
                    "size": len(payload),
                    "sha256": hashlib.sha256(payload).hexdigest(),
                })
            instructions = _restore_instructions(detected_version, generated_at).encode("utf-8")
            bundle.writestr(prefix + "RESTORE-FIRST.md", instructions)
            manifest_files.append({
                "path": "RESTORE-FIRST.md",
                "size": len(instructions),
                "sha256": hashlib.sha256(instructions).hexdigest(),
            })
            manifest = {
                "schema_version": "1.0",
                "generated_at": generated_at,
                "version": detected_version,
                "source_fingerprint": source_fingerprint,
                "privacy": {"user_data": False, "credentials": False},
                "runtime_required_files": [
                    "scripts/python/workspace_cli.py",
                    "VERSION",
                    "config/maintenance-policy.json",
                ],
                "files": manifest_files,
            }
            bundle.writestr(
                prefix + "RECOVERY-KIT-MANIFEST.json",
                json.dumps(manifest, ensure_ascii=False, indent=2).encode("utf-8"),
            )
            sums = "\n".join(f"{item['sha256']}  {item['path']}" for item in manifest_files) + "\n"
            bundle.writestr(prefix + "SHA256SUMS.txt", sums.encode("utf-8"))
        current_source_files = _collect_source_files(source_root)
        if restic_path and is_link_or_reparse(restic_path):
            raise ValueError("UNSAFE_EXPORT_SOURCE_LINK: tools/windows/restic.exe")
        if restic_path and restic_path.is_file():
            current_source_files.append(("tools/windows/restic.exe", restic_path))
        if _source_fingerprint(current_source_files) != source_fingerprint:
            raise OSError(
                "SOURCE_CHANGED_DURING_EXPORT: recovery-kit source changed "
                "between inventory and archive completion"
            )
        verification = verify_recovery_kit(temp_archive)
        if not verification["valid"]:
            raise OSError(f"恢复工具包校验失败: {verification['issues'][:3]}")
        archive_hash = verification["archive_sha256"]
        temp_checksum.write_text(f"{archive_hash}  {archive.name}\n", encoding="utf-8")
        os.replace(temp_archive, archive)
        os.replace(temp_checksum, checksum)
    finally:
        for path in (temp_archive, temp_checksum):
            if path.exists():
                path.unlink()
    final_verification = verify_recovery_kit(archive)
    return {
        **preview,
        "status": "created",
        "archive_sha256": final_verification["archive_sha256"],
        "archive_bytes": archive.stat().st_size,
        "verification": final_verification,
    }
