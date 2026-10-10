"""原子快照、完整性验证、隔离恢复和可回收保留策略。"""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from path_safety import is_link_or_reparse, is_reparse_point, link_escapes_root

MANIFEST_NAME = "WORKSPACE-SNAPSHOT-MANIFEST.json"
CACHE_DIRECTORY_NAMES = {".vs", "__pycache__", ".pytest_cache", "node_modules", ".venv"}
CACHE_FILE_SUFFIXES = {".ipch", ".pch", ".pyc", ".pyo"}


def _resolved(path: str | Path) -> Path:
    return Path(path).expanduser().resolve()


def _is_within(path: Path, parent: Path) -> bool:
    try:
        path.relative_to(parent)
        return True
    except ValueError:
        return False


def _validate_non_root(path: Path, label: str) -> None:
    if path == Path(path.anchor):
        raise ValueError(f"拒绝把磁盘根目录作为{label}")


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _safe_member(root: Path, relative: str) -> Path:
    candidate = (root / Path(relative)).resolve(strict=False)
    if not _is_within(candidate, root):
        raise ValueError(f"清单包含越界路径: {relative}")
    return candidate


def _inventory(
    root: Path,
    exclude_rebuildable_cache: bool = False,
) -> dict[str, Any]:
    files: list[dict[str, Any]] = []
    directories: list[str] = []
    symlinks: list[dict[str, str]] = []
    total_bytes = 0
    for current, dirnames, filenames in os.walk(root, followlinks=False):
        current_path = Path(current)
        for name in list(dirnames):
            path = current_path / name
            relative = path.relative_to(root).as_posix()
            if is_link_or_reparse(path):
                if (
                    (is_reparse_point(path) and not path.is_symlink())
                    or link_escapes_root(path, root)
                ):
                    raise ValueError(f"UNSAFE_REPARSE_POINT: {relative}")
                symlinks.append({"path": relative, "target": os.readlink(path)})
                dirnames.remove(name)
            elif exclude_rebuildable_cache and name in CACHE_DIRECTORY_NAMES:
                dirnames.remove(name)
            else:
                directories.append(relative)
        for name in filenames:
            path = current_path / name
            if path.name == MANIFEST_NAME and path.parent == root:
                continue
            if exclude_rebuildable_cache and path.suffix.lower() in CACHE_FILE_SUFFIXES:
                continue
            relative = path.relative_to(root).as_posix()
            if is_link_or_reparse(path):
                if (
                    (is_reparse_point(path) and not path.is_symlink())
                    or link_escapes_root(path, root)
                ):
                    raise ValueError(f"UNSAFE_REPARSE_POINT: {relative}")
                symlinks.append({"path": relative, "target": os.readlink(path)})
                continue
            size = path.stat().st_size
            files.append({"path": relative, "size": size, "sha256": _sha256(path)})
            total_bytes += size
    return {
        "files": sorted(files, key=lambda item: item["path"]),
        "directories": sorted(directories),
        "symlinks": sorted(symlinks, key=lambda item: item["path"]),
        "total_bytes": total_bytes,
    }


def _inventory_sha256(inventory: dict[str, Any]) -> str:
    payload = json.dumps(
        inventory,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _rebuildable_cache_inventory(root: Path) -> dict[str, Any]:
    files = 0
    total_bytes = 0
    roots: list[str] = []
    for current, dirnames, filenames in os.walk(root):
        current_path = Path(current)
        dirnames[:] = [
            name for name in dirnames
            if not is_link_or_reparse(current_path / name)
        ]
        if current_path.name in CACHE_DIRECTORY_NAMES:
            roots.append(current_path.relative_to(root).as_posix())
            for child_root, child_dirs, child_files in os.walk(current_path):
                child_path = Path(child_root)
                child_dirs[:] = [
                    name for name in child_dirs
                    if not is_link_or_reparse(child_path / name)
                ]
                for name in child_files:
                    try:
                        total_bytes += (Path(child_root) / name).stat().st_size
                        files += 1
                    except OSError:
                        pass
            dirnames[:] = []
            continue
        for name in filenames:
            if Path(name).suffix.lower() in CACHE_FILE_SUFFIXES:
                try:
                    total_bytes += (current_path / name).stat().st_size
                    files += 1
                except OSError:
                    pass
    return {
        "profile": "rebuildable-cache",
        "excluded_files": files,
        "excluded_bytes": total_bytes,
        "cache_roots": roots,
        "directory_names": sorted(CACHE_DIRECTORY_NAMES),
        "file_suffixes": sorted(CACHE_FILE_SUFFIXES),
    }


def _ignore_rebuildable_cache(directory: str, names: list[str]) -> set[str]:
    ignored = set()
    for name in names:
        path = Path(directory) / name
        if (path.is_dir() and name in CACHE_DIRECTORY_NAMES) or (path.is_file() and path.suffix.lower() in CACHE_FILE_SUFFIXES):
            ignored.add(name)
    return ignored


def _load_manifest(snapshot: Path) -> dict[str, Any]:
    manifest_path = snapshot / MANIFEST_NAME
    if not manifest_path.is_file() or is_link_or_reparse(manifest_path):
        raise ValueError(f"快照缺少 {MANIFEST_NAME}: {snapshot}")
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise ValueError(f"快照清单不可读: {manifest_path}") from exc
    if not isinstance(manifest, dict) or not isinstance(manifest.get("files"), list):
        raise ValueError(f"快照清单结构无效: {manifest_path}")
    return manifest


def _write_backup_status(workspace: Path, data: dict[str, Any]) -> Path:
    target = workspace / "07_Admin" / "WorkspaceOS" / "backup-status.json"
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_name(f".{target.name}.{uuid.uuid4().hex}.tmp")
    temporary.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(target)
    return target


def _write_verification_evidence(workspace: Path, data: dict[str, Any]) -> Path:
    target = workspace / "08_Indexes" / "BackupVerification" / "latest-snapshot-verification.json"
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_name(f".{target.name}.{uuid.uuid4().hex}.tmp")
    temporary.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(target)
    return target


def set_snapshot_pin(snapshot: str | Path, pinned: bool = True) -> dict[str, Any]:
    """固定或取消固定快照；固定快照不参与自动淘汰。"""
    root = _resolved(snapshot)
    manifest = _load_manifest(root)
    manifest["pinned"] = pinned
    manifest["pin_updated_at"] = datetime.now(timezone.utc).isoformat()
    target = root / MANIFEST_NAME
    temporary = target.with_name(f".{target.name}.{uuid.uuid4().hex}.tmp")
    temporary.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(target)
    return {"snapshot": str(root), "pinned": pinned, "manifest": str(target)}


def verify_snapshot(snapshot: str | Path) -> dict[str, Any]:
    """完整校验快照中的路径、大小、哈希、目录和符号链接。"""
    root = _resolved(snapshot)
    if not root.is_dir():
        raise ValueError(f"快照不存在或不是目录: {root}")
    manifest = _load_manifest(root)
    manifest_sha256 = _sha256(root / MANIFEST_NAME)
    issues: list[dict[str, str]] = []
    expected_files: set[str] = set()
    expected_directories = set(manifest.get("directories", []))
    expected_symlinks = {item["path"]: item["target"] for item in manifest.get("symlinks", [])}

    for item in manifest["files"]:
        relative = item.get("path")
        if not isinstance(relative, str):
            issues.append({"code": "INVALID_ENTRY", "path": str(relative)})
            continue
        try:
            path = _safe_member(root, relative)
        except ValueError:
            issues.append({"code": "PATH_TRAVERSAL", "path": relative})
            continue
        expected_files.add(relative)
        if not path.is_file() or is_link_or_reparse(path):
            issues.append({"code": "MISSING_FILE", "path": relative})
            continue
        if path.stat().st_size != item.get("size"):
            issues.append({"code": "SIZE_MISMATCH", "path": relative})
            continue
        if _sha256(path) != item.get("sha256"):
            issues.append({"code": "HASH_MISMATCH", "path": relative})

    actual = _inventory(root)
    actual_files = {item["path"] for item in actual["files"]}
    actual_directories = set(actual["directories"])
    actual_symlinks = {item["path"]: item["target"] for item in actual["symlinks"]}
    for relative in sorted(actual_files - expected_files):
        issues.append({"code": "UNEXPECTED_FILE", "path": relative})
    if "directories" in manifest:
        for relative in sorted(expected_directories - actual_directories):
            issues.append({"code": "MISSING_DIRECTORY", "path": relative})
        for relative in sorted(actual_directories - expected_directories):
            issues.append({"code": "UNEXPECTED_DIRECTORY", "path": relative})
    for relative, target in expected_symlinks.items():
        if actual_symlinks.get(relative) != target:
            issues.append({"code": "SYMLINK_MISMATCH", "path": relative})
    for relative in sorted(set(actual_symlinks) - set(expected_symlinks)):
        issues.append({"code": "UNEXPECTED_SYMLINK", "path": relative})

    consistency = manifest.get("source_consistency")
    source_consistency_verified = bool(
        isinstance(consistency, dict)
        and consistency.get("verified") is True
        and consistency.get("algorithm") == "sha256"
        and consistency.get("before_inventory_sha256")
        == consistency.get("after_inventory_sha256")
        == consistency.get("snapshot_inventory_sha256")
        == _inventory_sha256(actual)
    )
    if isinstance(consistency, dict) and not source_consistency_verified:
        issues.append({
            "code": "SNAPSHOT_INVENTORY_DIGEST_MISMATCH",
            "path": MANIFEST_NAME,
        })

    valid = not issues
    return {
        "snapshot": str(root),
        "valid": valid,
        "status": "valid" if valid else "invalid",
        "checked_at": datetime.now(timezone.utc).isoformat(),
        "checked_files": len(expected_files),
        "manifest_sha256": manifest_sha256,
        "manifest_schema_version": manifest.get("schema_version"),
        "source_consistency_verified": source_consistency_verified,
        "snapshot_inventory_sha256": _inventory_sha256(actual),
        "issues": issues,
    }


def create_snapshot(
    workspace: str | Path,
    destination: str | Path,
    apply: bool = False,
    snapshot_name: str | None = None,
    exclude_rebuildable_cache: bool = False,
) -> dict[str, Any]:
    """预览或原子创建完整快照；完成前执行全量校验。"""
    source = _resolved(workspace)
    destination_root = _resolved(destination)
    if not source.is_dir():
        raise ValueError(f"Workspace 不存在或不是目录: {source}")
    if not (source / ".workspace-os.json").is_file():
        raise ValueError(f"缺少 .workspace-os.json，拒绝将非 Workspace 目录作为源: {source}")
    _validate_non_root(destination_root, "快照目标")
    if _is_within(destination_root, source):
        raise ValueError("快照目标不能位于 Workspace 内部")

    name = snapshot_name or f"{source.name}_{datetime.now().strftime('%Y%m%d-%H%M%S')}"
    if not name or name in {".", ".."} or any(char in name for char in '<>:"/\\|?*'):
        raise ValueError("快照名称为空或包含跨平台非法字符")
    target = destination_root / name
    result: dict[str, Any] = {
        "workspace": str(source),
        "destination": str(target),
        "mode": "apply" if apply else "dry-run",
        "status": "planned",
    }
    exclusions = _rebuildable_cache_inventory(source) if exclude_rebuildable_cache else None
    if exclusions:
        result["exclusions"] = exclusions
    if target.exists():
        raise FileExistsError(f"快照目标已存在，拒绝覆盖: {target}")
    if not apply:
        return result

    destination_root.mkdir(parents=True, exist_ok=True)
    staging = destination_root / f".{name}.partial-{uuid.uuid4().hex}"
    try:
        before_inventory = _inventory(
            source,
            exclude_rebuildable_cache=exclude_rebuildable_cache,
        )
        shutil.copytree(
            source,
            staging,
            symlinks=True,
            ignore=_ignore_rebuildable_cache if exclude_rebuildable_cache else None,
        )
        inventory = _inventory(staging)
        after_inventory = _inventory(
            source,
            exclude_rebuildable_cache=exclude_rebuildable_cache,
        )
        before_digest = _inventory_sha256(before_inventory)
        after_digest = _inventory_sha256(after_inventory)
        snapshot_digest = _inventory_sha256(inventory)
        if before_digest != after_digest:
            raise OSError(
                "SOURCE_CHANGED_DURING_SNAPSHOT: source inventory changed "
                "between the pre-copy and post-copy checks"
            )
        if after_digest != snapshot_digest:
            raise OSError(
                "SOURCE_SNAPSHOT_MISMATCH: copied snapshot does not match "
                "the stable source inventory"
            )
        manifest = {
            "schema_version": "1.2",
            "created_at": datetime.now(timezone.utc).isoformat(),
            "source": str(source),
            "file_count": len(inventory["files"]),
            "directory_count": len(inventory["directories"]),
            "symlink_count": len(inventory["symlinks"]),
            "exclusions": exclusions,
            "source_consistency": {
                "verified": True,
                "algorithm": "sha256",
                "before_inventory_sha256": before_digest,
                "after_inventory_sha256": after_digest,
                "snapshot_inventory_sha256": snapshot_digest,
                "checked_at": datetime.now(timezone.utc).isoformat(),
            },
            **inventory,
        }
        manifest_path = staging / MANIFEST_NAME
        manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
        verification = verify_snapshot(staging)
        if not verification["valid"]:
            raise OSError(f"快照校验失败: {verification['issues'][:3]}")
        staging.replace(target)
        verification["snapshot"] = str(target)
    except Exception:
        if staging.exists():
            shutil.rmtree(staging)
        raise

    status = {
        "schema_version": "1.0",
        "last_snapshot_at": manifest["created_at"],
        "last_snapshot": str(target),
        "verified": True,
        "verified_at": verification["checked_at"],
        "file_count": manifest["file_count"],
        "total_bytes": manifest["total_bytes"],
        "exclusions": exclusions,
    }
    status_path = _write_backup_status(source, status)
    verification_path = _write_verification_evidence(source, verification)
    result.update(
        status="created",
        manifest=str(target / MANIFEST_NAME),
        backup_status=str(status_path),
        verification_report=str(verification_path),
        verified=True,
        source_consistency_verified=True,
        file_count=manifest["file_count"],
        total_bytes=manifest["total_bytes"],
        exclusions=exclusions,
    )
    return result


def restore_snapshot(snapshot: str | Path, destination: str | Path, apply: bool = False) -> dict[str, Any]:
    """先校验，再恢复到全新隔离目录；永不覆盖现有目标。"""
    source = _resolved(snapshot)
    target = _resolved(destination)
    _validate_non_root(target, "恢复目标")
    verification = verify_snapshot(source)
    result: dict[str, Any] = {
        "snapshot": str(source),
        "destination": str(target),
        "mode": "apply" if apply else "dry-run",
        "verified": verification["valid"],
        "checked_files": verification["checked_files"],
        "status": "planned",
    }
    if not verification["valid"]:
        result["status"] = "blocked"
        result["issues"] = verification["issues"]
        return result
    if target.exists():
        raise FileExistsError(f"恢复目标已存在，拒绝覆盖: {target}")
    if not apply:
        return result

    manifest = _load_manifest(source)
    target.parent.mkdir(parents=True, exist_ok=True)
    staging = target.parent / f".{target.name}.restore-partial-{uuid.uuid4().hex}"
    try:
        staging.mkdir()
        for relative in manifest.get("directories", []):
            _safe_member(staging, relative).mkdir(parents=True, exist_ok=True)
        for item in manifest["files"]:
            src = _safe_member(source, item["path"])
            dst = _safe_member(staging, item["path"])
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dst)
        for item in manifest.get("symlinks", []):
            link = _safe_member(staging, item["path"])
            link.parent.mkdir(parents=True, exist_ok=True)
            os.symlink(item["target"], link, target_is_directory=(source / item["path"]).is_dir())
        (staging / MANIFEST_NAME).write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
        post_verification = verify_snapshot(staging)
        if not post_verification["valid"]:
            raise OSError(f"恢复后校验失败: {post_verification['issues'][:3]}")
        (staging / MANIFEST_NAME).unlink()
        staging.replace(target)
    except Exception:
        if staging.exists():
            shutil.rmtree(staging)
        raise
    result["status"] = "restored"
    result["post_verified"] = True
    return result


def _keep_newest_buckets(
    records: list[dict[str, Any]],
    count: int,
    key: Callable[[datetime], object],
) -> set[Path]:
    kept: set[Path] = set()
    buckets: set[object] = set()
    for record in records:
        bucket = key(record["created_at"])
        if bucket in buckets:
            continue
        if len(buckets) >= max(0, count):
            break
        buckets.add(bucket)
        kept.add(record["path"])
    return kept


def apply_retention(
    destination: str | Path,
    hourly: int = 24,
    daily: int = 30,
    weekly: int = 12,
    monthly: int = 12,
    apply: bool = False,
) -> dict[str, Any]:
    """按 GFS 桶保留快照；淘汰项移动到回收区而非永久删除。"""
    root = _resolved(destination)
    _validate_non_root(root, "快照目录")
    for value in (hourly, daily, weekly, monthly):
        if value < 0:
            raise ValueError("保留数量不能为负数")
    records: list[dict[str, Any]] = []
    if root.exists():
        for path in root.iterdir():
            if not path.is_dir() or path.name.startswith((".", "_")):
                continue
            try:
                manifest = _load_manifest(path)
                created = datetime.fromisoformat(manifest["created_at"].replace("Z", "+00:00"))
                if created.tzinfo is None:
                    created = created.replace(tzinfo=timezone.utc)
                records.append({"path": path, "created_at": created, "pinned": bool(manifest.get("pinned"))})
            except (ValueError, KeyError, TypeError):
                continue
    records.sort(key=lambda item: item["created_at"], reverse=True)
    kept: set[Path] = {record["path"] for record in records if record["pinned"]}
    if records:
        kept.add(records[0]["path"])
    kept |= _keep_newest_buckets(records, hourly, lambda dt: (dt.year, dt.month, dt.day, dt.hour))
    kept |= _keep_newest_buckets(records, daily, lambda dt: dt.date())
    kept |= _keep_newest_buckets(records, weekly, lambda dt: (dt.isocalendar().year, dt.isocalendar().week))
    kept |= _keep_newest_buckets(records, monthly, lambda dt: (dt.year, dt.month))
    candidates = [record["path"] for record in records if record["path"] not in kept]
    result: dict[str, Any] = {
        "destination": str(root),
        "mode": "apply" if apply else "dry-run",
        "snapshot_count": len(records),
        "keep": [str(path) for path in sorted(kept)],
        "move_to_trash": [str(path) for path in candidates],
        "moved": [],
    }
    if not apply or not candidates:
        return result
    trash = root / "_WorkspaceOS_Trash" / datetime.now().strftime("%Y%m%d-%H%M%S")
    trash.mkdir(parents=True, exist_ok=False)
    for source in candidates:
        target = trash / source.name
        if target.exists():
            raise FileExistsError(f"回收区目标已存在，拒绝覆盖: {target}")
        shutil.move(str(source), str(target))
        result["moved"].append({"from": str(source), "to": str(target)})
    return result
