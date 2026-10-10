"""Verified offline device handoff bundles with zero-overwrite import."""
from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import uuid
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from archive_safety import inspect_zip_members, safe_relative_path
from device_sync import (
    _canonical_hash,
    _has_symlink_parent,
    _safe_workspace_member,
    _sha256,
    build_device_manifest,
    build_sync_receipt,
    compare_device_manifests,
    save_json_atomic,
)
from path_safety import is_link_or_reparse

SCHEMA_VERSION = "1.0"
SAFE_NAME = re.compile(r"[^A-Za-z0-9._-]+")


def _archive_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(4 * 1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _manifest_inventory_hash(manifest: dict[str, Any]) -> str:
    inventory = [
        {
            "path": item.get("path"),
            "type": item.get("type"),
            "size": item.get("size"),
            "sha256": item.get("sha256"),
            "target": item.get("target"),
        }
        for item in manifest.get("files", [])
    ]
    return _canonical_hash(inventory)


def _safe_device_name(value: str) -> str:
    cleaned = SAFE_NAME.sub("-", value.strip()).strip("-.")
    return cleaned[:48] or "device"


def _verify_bundle_data(
    archive: Path,
) -> tuple[dict[str, Any], dict[str, Any], str, list[dict[str, Any]], int]:
    issues: list[dict[str, Any]] = []
    checked = 0
    bundle_manifest: dict[str, Any] = {}
    device_manifest: dict[str, Any] = {}
    prefix = ""
    try:
        with zipfile.ZipFile(archive) as bundle:
            infos = bundle.infolist()
            issues.extend(inspect_zip_members(infos))
            names = [info.filename for info in infos if not info.filename.endswith("/")]
            bundle_manifests = [name for name in names if name.endswith("/HANDOFF-BUNDLE.json")]
            device_manifests = [name for name in names if name.endswith("/DEVICE-MANIFEST.json")]
            if len(bundle_manifests) != 1:
                issues.append({"code": "BUNDLE_MANIFEST_COUNT_INVALID", "count": len(bundle_manifests)})
                return bundle_manifest, device_manifest, prefix, issues, checked
            if len(device_manifests) != 1:
                issues.append({"code": "DEVICE_MANIFEST_COUNT_INVALID", "count": len(device_manifests)})
                return bundle_manifest, device_manifest, prefix, issues, checked
            bundle_manifest_name = bundle_manifests[0]
            prefix = bundle_manifest_name[: -len("HANDOFF-BUNDLE.json")]
            if device_manifests[0] != prefix + "DEVICE-MANIFEST.json":
                issues.append({"code": "MANIFEST_PREFIX_MISMATCH", "path": device_manifests[0]})
            bundle_manifest = json.loads(bundle.read(bundle_manifest_name).decode("utf-8-sig"))
            device_manifest = json.loads(bundle.read(device_manifests[0]).decode("utf-8-sig"))
            if bundle_manifest.get("schema_version") != SCHEMA_VERSION:
                issues.append({"code": "BUNDLE_SCHEMA_INVALID"})
            if device_manifest.get("schema_version") != "1.0":
                issues.append({"code": "DEVICE_MANIFEST_SCHEMA_INVALID"})
            if _manifest_inventory_hash(device_manifest) != device_manifest.get("inventory_sha256"):
                issues.append({"code": "DEVICE_INVENTORY_HASH_MISMATCH"})
            if bundle_manifest.get("source_inventory_sha256") != device_manifest.get("inventory_sha256"):
                issues.append({"code": "BUNDLE_DEVICE_INVENTORY_MISMATCH"})
            if bundle_manifest.get("workspace_instance") != device_manifest.get("workspace_instance"):
                issues.append({"code": "BUNDLE_WORKSPACE_INSTANCE_MISMATCH"})
            if bundle_manifest.get("scopes") != device_manifest.get("scopes"):
                issues.append({"code": "BUNDLE_SCOPE_MISMATCH"})
            if bundle_manifest.get("source_device") != device_manifest.get("device_id"):
                issues.append({"code": "BUNDLE_SOURCE_DEVICE_MISMATCH"})
            if not bundle_manifest.get("transport_protection_confirmed") and not bundle_manifest.get("simulation"):
                issues.append({"code": "TRANSPORT_PROTECTION_NOT_CONFIRMED"})

            manifest_files = bundle_manifest.get("files", [])
            if not isinstance(manifest_files, list):
                issues.append({"code": "BUNDLE_FILES_INVALID"})
                manifest_files = []
            expected = {
                bundle_manifest_name,
                prefix + "DEVICE-MANIFEST.json",
                prefix + "SHA256SUMS.txt",
            }
            bundle_paths: set[str] = set()
            for item in manifest_files:
                relative = item.get("path")
                if not safe_relative_path(relative):
                    issues.append({"code": "UNSAFE_MANIFEST_PATH", "path": str(relative)})
                    continue
                if relative in bundle_paths:
                    issues.append({"code": "DUPLICATE_BUNDLE_PATH", "path": relative})
                    continue
                bundle_paths.add(relative)
                member = prefix + "PAYLOAD/" + relative
                expected.add(member)
                if member not in names:
                    issues.append({"code": "BUNDLE_FILE_MISSING", "path": relative})
                    continue
                payload = bundle.read(member)
                checked += 1
                if len(payload) != item.get("size"):
                    issues.append({"code": "BUNDLE_SIZE_MISMATCH", "path": relative})
                elif hashlib.sha256(payload).hexdigest() != item.get("sha256"):
                    issues.append({"code": "BUNDLE_HASH_MISMATCH", "path": relative})
            device_files = {
                item.get("path"): item
                for item in device_manifest.get("files", [])
                if item.get("type") == "file" and item.get("sha256")
            }
            if set(device_files) != bundle_paths:
                issues.append({"code": "BUNDLE_DEVICE_FILE_SET_MISMATCH"})
            else:
                for relative, item in device_files.items():
                    bundle_item = next(entry for entry in manifest_files if entry.get("path") == relative)
                    if (
                        bundle_item.get("size") != item.get("size")
                        or bundle_item.get("sha256") != item.get("sha256")
                    ):
                        issues.append({"code": "BUNDLE_DEVICE_FILE_HASH_MISMATCH", "path": relative})
            if bundle_manifest.get("file_count") != len(manifest_files):
                issues.append({"code": "BUNDLE_FILE_COUNT_MISMATCH"})
            if bundle_manifest.get("total_bytes") != sum(
                int(item.get("size") or 0) for item in manifest_files
            ):
                issues.append({"code": "BUNDLE_TOTAL_BYTES_MISMATCH"})
            expected_sums = (
                "\n".join(
                    f"{item.get('sha256')}  PAYLOAD/{item.get('path')}"
                    for item in manifest_files
                )
                + "\n"
            )
            try:
                actual_sums = bundle.read(prefix + "SHA256SUMS.txt").decode("utf-8-sig")
                if actual_sums != expected_sums:
                    issues.append({"code": "BUNDLE_SUMS_MISMATCH"})
            except (KeyError, UnicodeDecodeError):
                issues.append({"code": "BUNDLE_SUMS_INVALID"})
            for unexpected in sorted(set(names) - expected):
                issues.append({"code": "UNEXPECTED_BUNDLE_MEMBER", "path": unexpected})
    except (
        OSError,
        zipfile.BadZipFile,
        UnicodeDecodeError,
        json.JSONDecodeError,
        KeyError,
        TypeError,
        StopIteration,
        AttributeError,
        ValueError,
    ) as exc:
        issues.append({"code": "BUNDLE_ARCHIVE_INVALID", "detail": type(exc).__name__})
    return bundle_manifest, device_manifest, prefix, issues, checked


def verify_device_bundle(archive: str | Path) -> dict[str, Any]:
    path = Path(archive).expanduser().resolve()
    if not path.is_file():
        return {
            "schema_version": SCHEMA_VERSION,
            "archive": str(path),
            "valid": False,
            "checked_files": 0,
            "issues": [{"code": "BUNDLE_MISSING", "path": str(path)}],
        }
    manifest, device, _, issues, checked = _verify_bundle_data(path)
    archive_hash = _archive_sha256(path)
    checksum_path = path.with_suffix(".sha256")
    if not checksum_path.is_file():
        issues.append({"code": "BUNDLE_CHECKSUM_MISSING", "path": str(checksum_path)})
    else:
        try:
            checksum_parts = checksum_path.read_text(encoding="utf-8-sig").strip().split()
            expected_hash = checksum_parts[0].lower()
            expected_name = checksum_parts[1] if len(checksum_parts) > 1 else ""
            if expected_hash != archive_hash or expected_name != path.name:
                issues.append({"code": "BUNDLE_CHECKSUM_MISMATCH", "path": str(checksum_path)})
        except (OSError, UnicodeDecodeError, IndexError):
            issues.append({"code": "BUNDLE_CHECKSUM_INVALID", "path": str(checksum_path)})
    return {
        "schema_version": SCHEMA_VERSION,
        "archive": str(path),
        "checked_at": datetime.now(timezone.utc).isoformat(),
        "valid": not issues,
        "checked_files": checked,
        "source_device": device.get("device_id"),
        "source_inventory_sha256": device.get("inventory_sha256"),
        "workspace_instance": device.get("workspace_instance"),
        "simulation": bool(manifest.get("simulation")),
        "archive_sha256": archive_hash,
        "checksum": str(checksum_path),
        "issues": issues,
    }


def export_device_bundle(
    workspace: str | Path,
    device_id: str,
    destination: str | Path,
    *,
    scopes: list[str] | None = None,
    max_file_mb: int = 512,
    confirm_protected_transport: bool = False,
    simulation: bool = False,
    apply: bool = False,
    output: str | Path | None = None,
) -> dict[str, Any]:
    root = Path(workspace).expanduser().resolve()
    destination_root = Path(destination).expanduser().resolve()
    manifest = build_device_manifest(root, device_id, scopes=scopes, max_file_mb=max_file_mb)
    if manifest["status"] != "ready":
        raise ValueError("设备清单存在缺失作用域、未验证文件或跨平台名称碰撞，拒绝导出")
    if apply and not simulation and not confirm_protected_transport:
        raise ValueError("离线交接包含用户数据；实际导出前必须确认目标位于受保护传输介质")
    name = (
        f"WorkspaceOS-Handoff-{_safe_device_name(device_id)}-"
        f"{manifest['inventory_sha256'][:10]}"
    )
    archive = destination_root / f"{name}.zip"
    checksum = destination_root / f"{name}.sha256"
    report = {
        "schema_version": SCHEMA_VERSION,
        "mode": "apply" if apply else "dry-run",
        "status": "planned",
        "source_workspace": str(root),
        "source_device": manifest["device_id"],
        "workspace_instance": manifest["workspace_instance"],
        "source_inventory_sha256": manifest["inventory_sha256"],
        "archive": str(archive),
        "checksum": str(checksum),
        "file_count": manifest["file_count"],
        "total_bytes": manifest["total_bytes"],
        "contains_user_data": True,
        "credentials_excluded_by_scope": True,
        "transport_protection_confirmed": bool(confirm_protected_transport),
        "simulation": bool(simulation),
        "overwritten_files": 0,
        "deleted_files": 0,
    }
    if not apply:
        if output:
            save_json_atomic(report, output)
        return report
    destination_root.mkdir(parents=True, exist_ok=True)
    if archive.exists() or checksum.exists():
        if archive.is_file() and checksum.is_file():
            verification = verify_device_bundle(archive)
            expected = checksum.read_text(encoding="utf-8-sig").strip().split()[0].lower()
            if verification["valid"] and verification["archive_sha256"] == expected:
                result = {**report, "status": "existing-verified", "verification": verification}
                if output:
                    save_json_atomic(result, output)
                return result
        raise FileExistsError(f"交接包目标已存在且无法验证，拒绝覆盖: {archive}")

    prefix = name + "/"
    temporary_archive = destination_root / f".{name}.{uuid.uuid4().hex}.partial.zip"
    temporary_checksum = destination_root / f".{name}.{uuid.uuid4().hex}.partial.sha256"
    bundle_files: list[dict[str, Any]] = []
    try:
        with zipfile.ZipFile(temporary_archive, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as bundle:
            for item in manifest["files"]:
                relative = item["path"]
                source = _safe_workspace_member(root, relative)
                if (
                    item.get("type") != "file"
                    or not item.get("sha256")
                    or not source.is_file()
                    or is_link_or_reparse(source)
                    or source.stat().st_size != item["size"]
                    or _sha256(source) != item["sha256"]
                ):
                    raise ValueError(f"源文件在交接包构建前发生变化: {relative}")
                payload = source.read_bytes()
                bundle.writestr(prefix + "PAYLOAD/" + relative, payload)
                bundle_files.append({
                    "path": relative,
                    "size": len(payload),
                    "sha256": hashlib.sha256(payload).hexdigest(),
                })
            current = build_device_manifest(root, device_id, scopes=scopes, max_file_mb=max_file_mb)
            if current["inventory_sha256"] != manifest["inventory_sha256"]:
                raise ValueError("源 Workspace 在交接包构建期间发生变化")
            bundle_manifest = {
                "schema_version": SCHEMA_VERSION,
                "generated_at": datetime.now(timezone.utc).isoformat(),
                "source_device": manifest["device_id"],
                "workspace_instance": manifest["workspace_instance"],
                "source_inventory_sha256": manifest["inventory_sha256"],
                "scopes": manifest["scopes"],
                "max_file_mb": manifest["max_file_mb"],
                "file_count": len(bundle_files),
                "total_bytes": sum(item["size"] for item in bundle_files),
                "contains_user_data": True,
                "credentials_excluded_by_scope": True,
                "transport_protection_confirmed": bool(confirm_protected_transport),
                "simulation": bool(simulation),
                "files": bundle_files,
            }
            bundle.writestr(
                prefix + "DEVICE-MANIFEST.json",
                json.dumps(manifest, ensure_ascii=False, indent=2).encode("utf-8"),
            )
            bundle.writestr(
                prefix + "HANDOFF-BUNDLE.json",
                json.dumps(bundle_manifest, ensure_ascii=False, indent=2).encode("utf-8"),
            )
            sums = "\n".join(f"{item['sha256']}  PAYLOAD/{item['path']}" for item in bundle_files) + "\n"
            bundle.writestr(prefix + "SHA256SUMS.txt", sums.encode("utf-8"))
        archive_hash = _archive_sha256(temporary_archive)
        temporary_checksum.write_text(f"{archive_hash}  {archive.name}\n", encoding="utf-8")
        os.replace(temporary_archive, archive)
        os.replace(temporary_checksum, checksum)
        verification = verify_device_bundle(archive)
        if not verification["valid"] or verification["archive_sha256"] != archive_hash:
            raise ValueError("交接包提交后校验失败")
        result = {
            **report,
            "status": "exported",
            "archive_sha256": archive_hash,
            "archive_bytes": archive.stat().st_size,
            "verification": verification,
        }
    except Exception:
        for temporary in (temporary_archive, temporary_checksum):
            try:
                temporary.unlink()
            except OSError:
                pass
        raise
    if output:
        save_json_atomic(result, output)
    return result


def _recover_import_transactions(target_root: Path) -> tuple[int, list[dict[str, Any]]]:
    staging_root = target_root / "08_Indexes" / "Devices" / "BundleStaging"
    if not staging_root.is_dir():
        return 0, []
    recovered = 0
    issues: list[dict[str, Any]] = []
    for transaction in sorted(staging_root.iterdir()):
        if not transaction.is_dir():
            continue
        try:
            journal = json.loads((transaction / "transaction.json").read_text(encoding="utf-8-sig"))
            entries = journal["files"]
        except (OSError, UnicodeDecodeError, json.JSONDecodeError, KeyError, TypeError):
            issues.append({"code": "BUNDLE_TRANSACTION_UNREADABLE", "transaction": transaction.name})
            continue
        transaction_issues = []
        for entry in entries:
            relative = entry.get("path")
            expected = entry.get("sha256")
            if not isinstance(relative, str) or not isinstance(expected, str):
                transaction_issues.append({"code": "BUNDLE_TRANSACTION_ENTRY_INVALID"})
                continue
            target = _safe_workspace_member(target_root, relative)
            staged = _safe_workspace_member(transaction / "payload", relative)
            if target.is_file() and not staged.exists():
                if is_link_or_reparse(target) or _sha256(target) != expected:
                    transaction_issues.append({
                        "code": "BUNDLE_INTERRUPTED_TARGET_CHANGED",
                        "path": relative,
                    })
                    continue
                staged.parent.mkdir(parents=True, exist_ok=True)
                os.replace(target, staged)
            elif target.exists() and staged.exists():
                transaction_issues.append({"code": "BUNDLE_TRANSACTION_AMBIGUOUS", "path": relative})
        if transaction_issues:
            issues.extend(transaction_issues)
            continue
        shutil.rmtree(transaction)
        recovered += 1
    try:
        staging_root.rmdir()
    except OSError:
        pass
    return recovered, issues


def import_device_bundle(
    archive: str | Path,
    target_workspace: str | Path,
    target_device_id: str,
    *,
    apply: bool = False,
    output: str | Path | None = None,
) -> dict[str, Any]:
    archive_path = Path(archive).expanduser().resolve()
    target_root = Path(target_workspace).expanduser().resolve()
    report_path = (
        Path(output)
        if output
        else target_root / "08_Indexes" / "Devices" / "device-bundle-import.json"
    )
    verification = verify_device_bundle(archive_path)
    base_report = {
        "schema_version": SCHEMA_VERSION,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "mode": "apply" if apply else "dry-run",
        "archive": str(archive_path),
        "target_workspace": str(target_root),
        "target_device": target_device_id,
        "overwritten_files": 0,
        "deleted_files": 0,
        "verification": verification,
    }
    if not verification["valid"]:
        report = {**base_report, "status": "blocked", "issues": verification["issues"]}
        save_json_atomic(report, report_path)
        return report
    if not (target_root / ".workspace-os.json").is_file():
        raise ValueError(f"不是有效目标 Workspace: {target_root}")
    bundle_manifest, source_manifest, prefix, _, _ = _verify_bundle_data(archive_path)
    scopes = source_manifest["scopes"]
    max_file_mb = int(source_manifest.get("max_file_mb") or 512)
    staging_root = target_root / "08_Indexes" / "Devices" / "BundleStaging"
    pending_transactions = (
        [path for path in staging_root.iterdir() if path.is_dir()]
        if staging_root.is_dir()
        else []
    )
    if pending_transactions and not apply:
        report = {
            **base_report,
            "status": "blocked",
            "issues": [{
                "code": "INTERRUPTED_BUNDLE_TRANSACTION_PENDING",
                "count": len(pending_transactions),
            }],
        }
        save_json_atomic(report, report_path)
        return report
    recovered, recovery_issues = (
        _recover_import_transactions(target_root) if apply else (0, [])
    )
    if recovery_issues:
        report = {
            **base_report,
            "status": "blocked",
            "recovered_transactions": recovered,
            "issues": recovery_issues,
        }
        save_json_atomic(report, report_path)
        return report
    target_manifest = build_device_manifest(
        target_root,
        target_device_id,
        scopes=scopes,
        max_file_mb=max_file_mb,
    )
    if target_manifest["workspace_instance"] != source_manifest["workspace_instance"]:
        report = {
            **base_report,
            "status": "blocked",
            "issues": [{"code": "WORKSPACE_INSTANCE_MISMATCH"}],
        }
        save_json_atomic(report, report_path)
        return report
    comparison = compare_device_manifests(source_manifest, target_manifest)
    if comparison["status"] != "ready":
        report = {
            **base_report,
            "status": "blocked",
            "comparison": comparison,
            "issues": [{"code": "BUNDLE_IMPORT_CONFLICT"}],
        }
        save_json_atomic(report, report_path)
        return report
    source_only = comparison["source_only"]
    if not source_only:
        receipt = build_sync_receipt(source_manifest, target_manifest)
        report = {
            **base_report,
            "status": "already-synced",
            "comparison": comparison,
            "receipt": receipt,
            "copied_files": 0,
            "copied_bytes": 0,
            "issues": [],
        }
        save_json_atomic(report, report_path)
        return report
    copied_bytes = sum(
        int(item.get("size") or 0)
        for item in source_manifest["files"]
        if item["path"] in source_only
    )
    if not apply:
        report = {
            **base_report,
            "status": "planned",
            "comparison": comparison,
            "copied_files": 0,
            "planned_files": len(source_only),
            "copied_bytes": 0,
            "planned_bytes": copied_bytes,
            "issues": [],
        }
        save_json_atomic(report, report_path)
        return report

    current_target = build_device_manifest(
        target_root,
        target_device_id,
        scopes=scopes,
        max_file_mb=max_file_mb,
    )
    if current_target["inventory_sha256"] != target_manifest["inventory_sha256"]:
        report = {
            **base_report,
            "status": "blocked",
            "issues": [{"code": "TARGET_CHANGED_BEFORE_IMPORT"}],
        }
        save_json_atomic(report, report_path)
        return report

    file_map = {item["path"]: item for item in bundle_manifest["files"]}
    transaction = staging_root / uuid.uuid4().hex
    payload_root = transaction / "payload"
    transaction.mkdir(parents=True, exist_ok=False)
    entries = [
        {"path": relative, "size": file_map[relative]["size"], "sha256": file_map[relative]["sha256"]}
        for relative in source_only
    ]
    save_json_atomic({
        "schema_version": SCHEMA_VERSION,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "state": "staging",
        "archive_sha256": verification["archive_sha256"],
        "target_inventory_sha256": target_manifest["inventory_sha256"],
        "files": entries,
    }, transaction / "transaction.json")
    committed: list[tuple[Path, Path]] = []
    created_directories: list[Path] = []
    try:
        with zipfile.ZipFile(archive_path) as bundle:
            for entry in entries:
                relative = entry["path"]
                target = _safe_workspace_member(target_root, relative)
                staged = _safe_workspace_member(payload_root, relative)
                if target.exists() or is_link_or_reparse(target):
                    raise FileExistsError(f"目标已存在，拒绝覆盖: {relative}")
                if _has_symlink_parent(target, target_root):
                    raise ValueError(f"目标父目录包含符号链接，拒绝写入: {relative}")
                payload = bundle.read(prefix + "PAYLOAD/" + relative)
                if (
                    len(payload) != entry["size"]
                    or hashlib.sha256(payload).hexdigest() != entry["sha256"]
                ):
                    raise ValueError(f"交接包内容回读校验失败: {relative}")
                staged.parent.mkdir(parents=True, exist_ok=True)
                staged.write_bytes(payload)
                if _sha256(staged) != entry["sha256"]:
                    raise OSError(f"staging 回读失败: {relative}")
        target_still = build_device_manifest(
            target_root,
            target_device_id,
            scopes=scopes,
            max_file_mb=max_file_mb,
        )
        if target_still["inventory_sha256"] != target_manifest["inventory_sha256"]:
            raise ValueError("提交前目标 Workspace 已变化")
        journal_path = transaction / "transaction.json"
        journal = json.loads(journal_path.read_text(encoding="utf-8-sig"))
        journal["state"] = "committing"
        save_json_atomic(journal, journal_path)
        for entry in entries:
            relative = entry["path"]
            staged = _safe_workspace_member(payload_root, relative)
            target = _safe_workspace_member(target_root, relative)
            if target.exists() or is_link_or_reparse(target):
                raise FileExistsError(f"提交时目标已存在，拒绝覆盖: {relative}")
            missing = []
            parent = target.parent
            while parent != target_root and not parent.exists():
                missing.append(parent)
                parent = parent.parent
            target.parent.mkdir(parents=True, exist_ok=True)
            created_directories.extend(reversed(missing))
            os.replace(staged, target)
            committed.append((target, staged))
        final_target = build_device_manifest(
            target_root,
            target_device_id,
            scopes=scopes,
            max_file_mb=max_file_mb,
        )
        receipt = build_sync_receipt(source_manifest, final_target)
        if receipt["status"] != "verified":
            raise OSError("导入后目标库存与源库存不一致")
        shutil.rmtree(transaction)
        try:
            staging_root.rmdir()
        except OSError:
            pass
        report = {
            **base_report,
            "status": "verified",
            "comparison": comparison,
            "receipt": receipt,
            "copied_files": len(entries),
            "copied_bytes": copied_bytes,
            "recovered_transactions": recovered,
            "issues": [],
        }
    except (OSError, ValueError, KeyError, zipfile.BadZipFile) as exc:
        for target, staged in reversed(committed):
            if target.is_file() and not staged.exists():
                staged.parent.mkdir(parents=True, exist_ok=True)
                os.replace(target, staged)
        for directory in reversed(created_directories):
            try:
                directory.rmdir()
            except OSError:
                pass
        shutil.rmtree(transaction, ignore_errors=True)
        try:
            staging_root.rmdir()
        except OSError:
            pass
        report = {
            **base_report,
            "status": "failed",
            "copied_files": 0,
            "copied_bytes": 0,
            "recovered_transactions": recovered,
            "issues": [{"code": "BUNDLE_IMPORT_FAILED", "message": str(exc)}],
        }
    save_json_atomic(report, report_path)
    return report
