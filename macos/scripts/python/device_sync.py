"""Privacy-preserving device manifests and conflict-safe handoff receipts."""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import unicodedata
import uuid
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import Any

from path_safety import is_link_or_reparse

DEFAULT_SCOPES = (
    "00_Inbox/Mobile",
    "02_Knowledge",
    "04_AI",
    "06_Release",
    "09_Templates",
)
SKIP_PARTS = {
    ".git",
    ".pytest_cache",
    ".venv",
    ".vs",
    "__pycache__",
    "_WorkspaceOS_Trash",
    "node_modules",
    "#recycle",
    "@eadir",
    "$recycle.bin",
}
SENSITIVE_SCOPE_PARTS = {"private", "accounts", "certificates", "secrets"}


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(4 * 1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _canonical_hash(value: Any) -> str:
    payload = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _normalize_scope(value: str) -> str:
    raw = value.replace("\\", "/").strip("/")
    path = PurePosixPath(raw)
    if not raw or path.is_absolute() or any(part in {"", ".", ".."} for part in path.parts):
        raise ValueError(f"同步作用域必须是 Workspace 内的相对路径: {value}")
    lowered_parts = {part.casefold() for part in path.parts}
    if path.parts[0].casefold() == "08_indexes":
        raise ValueError("08_Indexes 是设备本地派生数据，不能进入跨设备同步清单")
    if lowered_parts & SENSITIVE_SCOPE_PARTS:
        raise ValueError("Private、Accounts、Certificates 与 secrets 不能进入跨设备交接作用域")
    return path.as_posix()


def _portable_key(relative: str) -> str:
    return unicodedata.normalize("NFC", relative).casefold()


def build_device_manifest(
    workspace: str | Path,
    device_id: str,
    *,
    scopes: list[str] | tuple[str, ...] | None = None,
    max_file_mb: int = 512,
) -> dict[str, Any]:
    root = Path(workspace).expanduser().resolve()
    if not root.is_dir() or not (root / ".workspace-os.json").is_file():
        raise ValueError(f"不是有效 Workspace: {root}")
    clean_device_id = device_id.strip()
    if not clean_device_id or len(clean_device_id) > 128:
        raise ValueError("device_id 不能为空且不能超过 128 个字符")
    if max_file_mb < 1:
        raise ValueError("max_file_mb 至少为 1")
    normalized_scopes = sorted({
        _normalize_scope(value)
        for value in (scopes or DEFAULT_SCOPES)
    })
    max_bytes = max_file_mb * 1024 * 1024
    files: list[dict[str, Any]] = []
    missing_scopes: list[str] = []
    unverified: list[dict[str, Any]] = []

    for scope in normalized_scopes:
        scope_root = root.joinpath(*PurePosixPath(scope).parts)
        if not scope_root.exists():
            missing_scopes.append(scope)
            continue
        if not scope_root.is_dir():
            missing_scopes.append(scope)
            continue
        for current, dirnames, filenames in os.walk(scope_root, followlinks=False):
            current_path = Path(current)
            original_directories = list(dirnames)
            dirnames[:] = [
                name for name in dirnames
                if name.lower() not in {part.lower() for part in SKIP_PARTS}
                and not is_link_or_reparse(current_path / name)
            ]
            for name in sorted(set(original_directories) - set(dirnames)):
                linked = current_path / name
                if is_link_or_reparse(linked):
                    unverified.append({
                        "path": linked.relative_to(root).as_posix(),
                        "reason": "reparse_point",
                    })
            for name in sorted(filenames):
                path = current_path / name
                relative = path.relative_to(root).as_posix()
                try:
                    if is_link_or_reparse(path):
                        item = {
                            "path": relative,
                            "type": "symlink",
                            "target": os.readlink(path),
                            "size": 0,
                            "sha256": None,
                        }
                        files.append(item)
                        unverified.append({"path": relative, "reason": "symlink"})
                        continue
                    stat = path.stat()
                    if stat.st_size > max_bytes:
                        item = {
                            "path": relative,
                            "type": "file",
                            "size": stat.st_size,
                            "modified_ns": stat.st_mtime_ns,
                            "sha256": None,
                        }
                        files.append(item)
                        unverified.append({
                            "path": relative,
                            "reason": "size_limit",
                            "size": stat.st_size,
                        })
                        continue
                    files.append({
                        "path": relative,
                        "type": "file",
                        "size": stat.st_size,
                        "modified_ns": stat.st_mtime_ns,
                        "sha256": _sha256(path),
                    })
                except OSError as exc:
                    unverified.append({
                        "path": relative,
                        "reason": "read_error",
                        "error": str(exc),
                    })

    files.sort(key=lambda item: item["path"])
    collision_groups: dict[str, list[str]] = {}
    for item in files:
        collision_groups.setdefault(_portable_key(item["path"]), []).append(item["path"])
    collisions = [
        {"portable_key": key, "paths": sorted(paths)}
        for key, paths in collision_groups.items()
        if len(set(paths)) > 1
    ]
    inventory = [
        {
            "path": item["path"],
            "type": item["type"],
            "size": item.get("size"),
            "sha256": item.get("sha256"),
            "target": item.get("target"),
        }
        for item in files
    ]
    workspace_marker = json.loads((root / ".workspace-os.json").read_text(encoding="utf-8-sig"))
    blockers = len(missing_scopes) + len(unverified) + len(collisions)
    return {
        "schema_version": "1.0",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "device_id": clean_device_id,
        "workspace_instance": _canonical_hash(workspace_marker)[:24],
        "privacy_mode": "relative-paths-and-hashes",
        "scopes": normalized_scopes,
        "max_file_mb": max_file_mb,
        "status": "blocked" if blockers else "ready",
        "file_count": len(files),
        "total_bytes": sum(int(item.get("size") or 0) for item in files),
        "inventory_sha256": _canonical_hash(inventory),
        "missing_scopes": missing_scopes,
        "unverified": unverified,
        "portable_name_collisions": collisions,
        "files": files,
    }


def load_device_manifest(path: str | Path) -> dict[str, Any]:
    source = Path(path)
    try:
        value = json.loads(source.read_text(encoding="utf-8-sig"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"设备清单不可读: {source}") from exc
    if (
        not isinstance(value, dict)
        or value.get("schema_version") != "1.0"
        or not isinstance(value.get("files"), list)
        or not isinstance(value.get("device_id"), str)
    ):
        raise ValueError(f"设备清单结构无效: {source}")
    inventory = [
        {
            "path": item.get("path"),
            "type": item.get("type"),
            "size": item.get("size"),
            "sha256": item.get("sha256"),
            "target": item.get("target"),
        }
        for item in value["files"]
    ]
    if _canonical_hash(inventory) != value.get("inventory_sha256"):
        raise ValueError(f"设备清单库存摘要不匹配: {source}")
    return value


def compare_device_manifests(
    source_manifest: dict[str, Any],
    target_manifest: dict[str, Any],
) -> dict[str, Any]:
    source_files = {item["path"]: item for item in source_manifest["files"]}
    target_files = {item["path"]: item for item in target_manifest["files"]}
    same: list[str] = []
    source_only: list[str] = []
    target_only: list[str] = []
    conflicts: list[dict[str, Any]] = []
    for relative in sorted(set(source_files) | set(target_files)):
        source = source_files.get(relative)
        target = target_files.get(relative)
        if source is None:
            target_only.append(relative)
        elif target is None:
            source_only.append(relative)
        elif (
            source.get("type") == target.get("type")
            and source.get("size") == target.get("size")
            and source.get("sha256") is not None
            and source.get("sha256") == target.get("sha256")
            and source.get("target") == target.get("target")
        ):
            same.append(relative)
        else:
            conflicts.append({
                "path": relative,
                "source_size": source.get("size"),
                "target_size": target.get("size"),
                "source_sha256": source.get("sha256"),
                "target_sha256": target.get("sha256"),
            })
    scope_mismatch = source_manifest.get("scopes") != target_manifest.get("scopes")
    instance_mismatch = source_manifest.get("workspace_instance") != target_manifest.get("workspace_instance")
    same_device_id = source_manifest.get("device_id") == target_manifest.get("device_id")
    unverified = (
        list(source_manifest.get("unverified", []))
        + list(target_manifest.get("unverified", []))
    )
    collisions = (
        list(source_manifest.get("portable_name_collisions", []))
        + list(target_manifest.get("portable_name_collisions", []))
    )
    blockers = (
        len(target_only)
        + len(conflicts)
        + len(unverified)
        + len(collisions)
        + int(scope_mismatch)
        + int(instance_mismatch)
        + int(same_device_id)
        + len(source_manifest.get("missing_scopes", []))
        + len(target_manifest.get("missing_scopes", []))
    )
    return {
        "schema_version": "1.0",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "source_device": source_manifest["device_id"],
        "target_device": target_manifest["device_id"],
        "status": "ready" if blockers == 0 else "blocked",
        "safe_to_copy_source_to_target": blockers == 0,
        "summary": {
            "same": len(same),
            "source_only": len(source_only),
            "target_only": len(target_only),
            "conflicts": len(conflicts),
            "unverified": len(unverified),
            "portable_name_collisions": len(collisions),
        },
        "scope_mismatch": scope_mismatch,
        "workspace_instance_mismatch": instance_mismatch,
        "same_device_id": same_device_id,
        "same": same,
        "source_only": source_only,
        "target_only": target_only,
        "conflicts": conflicts,
        "unverified": unverified,
        "portable_name_collisions": collisions,
    }


def build_sync_receipt(
    source_manifest: dict[str, Any],
    target_manifest: dict[str, Any],
) -> dict[str, Any]:
    comparison = compare_device_manifests(source_manifest, target_manifest)
    exact_match = (
        comparison["status"] == "ready"
        and comparison["summary"]["source_only"] == 0
        and source_manifest["inventory_sha256"] == target_manifest["inventory_sha256"]
    )
    receipt_payload = {
        "source_device": source_manifest["device_id"],
        "target_device": target_manifest["device_id"],
        "source_inventory_sha256": source_manifest["inventory_sha256"],
        "target_inventory_sha256": target_manifest["inventory_sha256"],
        "scopes": source_manifest.get("scopes", []),
    }
    return {
        "schema_version": "1.0",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "status": "verified" if exact_match else "blocked",
        "safe_to_switch_primary_device": exact_match,
        "receipt_id": _canonical_hash(receipt_payload)[:24],
        **receipt_payload,
        "comparison": comparison,
    }


def save_json_atomic(value: dict[str, Any], output: str | Path) -> Path:
    target = Path(output)
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_name(f".{target.name}.{uuid.uuid4().hex}.tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(target)
    return target


def _safe_workspace_member(root: Path, relative: str) -> Path:
    normalized = _normalize_scope(relative)
    candidate = root.joinpath(*PurePosixPath(normalized).parts)
    resolved = candidate.resolve(strict=False)
    try:
        resolved.relative_to(root)
    except ValueError as exc:
        raise ValueError(f"交接路径逃逸 Workspace: {relative}") from exc
    return candidate


def _has_symlink_parent(path: Path, root: Path) -> bool:
    current = path.parent
    while current != root:
        if is_link_or_reparse(current):
            return True
        if root not in current.parents:
            return True
        current = current.parent
    return False


def _manifest_matches_current(root: Path, manifest: dict[str, Any]) -> tuple[bool, dict[str, Any]]:
    current = build_device_manifest(
        root,
        manifest["device_id"],
        scopes=manifest.get("scopes") or None,
        max_file_mb=int(manifest.get("max_file_mb") or 512),
    )
    return current["inventory_sha256"] == manifest.get("inventory_sha256"), current


def _handoff_report(
    *,
    source_root: Path,
    target_root: Path,
    source_manifest: dict[str, Any],
    target_manifest: dict[str, Any],
    status: str,
    mode: str,
    issues: list[dict[str, Any]],
    comparison: dict[str, Any] | None = None,
    copied_files: int = 0,
    copied_bytes: int = 0,
    receipt: dict[str, Any] | None = None,
    recovered_transactions: int = 0,
) -> dict[str, Any]:
    return {
        "schema_version": "1.0",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "status": status,
        "mode": mode,
        "source_workspace": str(source_root),
        "target_workspace": str(target_root),
        "source_device": source_manifest.get("device_id"),
        "target_device": target_manifest.get("device_id"),
        "source_inventory_sha256": source_manifest.get("inventory_sha256"),
        "target_inventory_before_sha256": target_manifest.get("inventory_sha256"),
        "copied_files": copied_files,
        "copied_bytes": copied_bytes,
        "overwritten_files": 0,
        "deleted_files": 0,
        "recovered_transactions": recovered_transactions,
        "comparison": comparison,
        "receipt": receipt,
        "issues": issues,
    }


def _recover_interrupted_handoffs(target_root: Path) -> tuple[int, list[dict[str, Any]]]:
    staging_root = target_root / "08_Indexes" / "Devices" / "HandoffStaging"
    if not staging_root.is_dir():
        return 0, []
    recovered = 0
    issues: list[dict[str, Any]] = []
    for transaction in sorted(staging_root.iterdir()):
        if not transaction.is_dir():
            continue
        journal_path = transaction / "transaction.json"
        try:
            journal = json.loads(journal_path.read_text(encoding="utf-8-sig"))
            entries = journal["files"]
            if not isinstance(entries, list):
                raise ValueError("files must be a list")
        except (OSError, UnicodeDecodeError, json.JSONDecodeError, KeyError, TypeError, ValueError) as exc:
            issues.append({
                "code": "INTERRUPTED_TRANSACTION_UNREADABLE",
                "transaction": transaction.name,
                "error": str(exc),
            })
            continue

        transaction_issues: list[dict[str, Any]] = []
        for entry in entries:
            relative = entry.get("path")
            expected_hash = entry.get("sha256")
            if not isinstance(relative, str) or not isinstance(expected_hash, str):
                transaction_issues.append({
                    "code": "INTERRUPTED_TRANSACTION_ENTRY_INVALID",
                    "transaction": transaction.name,
                })
                continue
            staged = _safe_workspace_member(transaction / "payload", relative)
            target = _safe_workspace_member(target_root, relative)
            if target.is_file() and not staged.exists():
                if is_link_or_reparse(target) or _sha256(target) != expected_hash:
                    transaction_issues.append({
                        "code": "INTERRUPTED_TARGET_CHANGED",
                        "transaction": transaction.name,
                        "path": relative,
                    })
                    continue
                staged.parent.mkdir(parents=True, exist_ok=True)
                os.replace(target, staged)
            elif target.exists() and staged.exists():
                transaction_issues.append({
                    "code": "INTERRUPTED_TRANSACTION_AMBIGUOUS",
                    "transaction": transaction.name,
                    "path": relative,
                })
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


def apply_source_only_handoff(
    source_workspace: str | Path,
    target_workspace: str | Path,
    source_manifest_path: str | Path,
    target_manifest_path: str | Path,
    *,
    apply: bool = False,
    output: str | Path | None = None,
) -> dict[str, Any]:
    """Copy only source-only files with staging, revalidation, and rollback."""
    source_root = Path(source_workspace).expanduser().resolve()
    target_root = Path(target_workspace).expanduser().resolve()
    if source_root == target_root:
        raise ValueError("源 Workspace 与目标 Workspace 不能相同")
    if not (source_root / ".workspace-os.json").is_file():
        raise ValueError(f"不是有效源 Workspace: {source_root}")
    if not (target_root / ".workspace-os.json").is_file():
        raise ValueError(f"不是有效目标 Workspace: {target_root}")
    source_manifest = load_device_manifest(source_manifest_path)
    target_manifest = load_device_manifest(target_manifest_path)
    mode = "apply" if apply else "dry-run"
    report_path = Path(output) if output else target_root / "08_Indexes" / "Devices" / "device-apply-status.json"

    staging_root = target_root / "08_Indexes" / "Devices" / "HandoffStaging"
    pending_transactions = (
        [path for path in staging_root.iterdir() if path.is_dir()]
        if staging_root.is_dir()
        else []
    )
    if pending_transactions and not apply:
        report = _handoff_report(
            source_root=source_root,
            target_root=target_root,
            source_manifest=source_manifest,
            target_manifest=target_manifest,
            status="blocked",
            mode=mode,
            issues=[{
                "code": "INTERRUPTED_TRANSACTION_PENDING",
                "message": "检测到中断事务；dry-run 不会修改目标，请使用 --apply 触发安全回滚",
                "count": len(pending_transactions),
            }],
        )
        save_json_atomic(report, report_path)
        return report
    recovered_transactions, recovery_issues = (
        _recover_interrupted_handoffs(target_root) if apply else (0, [])
    )
    if recovery_issues:
        report = _handoff_report(
            source_root=source_root,
            target_root=target_root,
            source_manifest=source_manifest,
            target_manifest=target_manifest,
            status="blocked",
            mode=mode,
            issues=recovery_issues,
            recovered_transactions=recovered_transactions,
        )
        save_json_atomic(report, report_path)
        return report

    source_matches, current_source = _manifest_matches_current(source_root, source_manifest)
    target_matches, current_target = _manifest_matches_current(target_root, target_manifest)
    freshness_issues: list[dict[str, Any]] = []
    if not source_matches:
        freshness_issues.append({"code": "SOURCE_MANIFEST_STALE", "message": "源 Workspace 在清单生成后已变化"})
    if not target_matches:
        freshness_issues.append({"code": "TARGET_MANIFEST_STALE", "message": "目标 Workspace 在清单生成后已变化"})
    if freshness_issues:
        report = _handoff_report(
            source_root=source_root,
            target_root=target_root,
            source_manifest=source_manifest,
            target_manifest=target_manifest,
            status="blocked",
            mode=mode,
            issues=freshness_issues,
            recovered_transactions=recovered_transactions,
        )
        save_json_atomic(report, report_path)
        return report

    comparison = compare_device_manifests(current_source, current_target)
    if comparison["status"] != "ready":
        report = _handoff_report(
            source_root=source_root,
            target_root=target_root,
            source_manifest=source_manifest,
            target_manifest=target_manifest,
            status="blocked",
            mode=mode,
            issues=[{"code": "HANDOFF_PLAN_BLOCKED", "message": "交接门禁未通过"}],
            comparison=comparison,
            recovered_transactions=recovered_transactions,
        )
        save_json_atomic(report, report_path)
        return report
    source_only = comparison["source_only"]
    if not source_only:
        receipt = build_sync_receipt(current_source, current_target)
        report = _handoff_report(
            source_root=source_root,
            target_root=target_root,
            source_manifest=source_manifest,
            target_manifest=target_manifest,
            status="already-synced",
            mode=mode,
            issues=[],
            comparison=comparison,
            receipt=receipt,
            recovered_transactions=recovered_transactions,
        )
        save_json_atomic(report, report_path)
        return report
    if not apply:
        report = _handoff_report(
            source_root=source_root,
            target_root=target_root,
            source_manifest=source_manifest,
            target_manifest=target_manifest,
            status="planned",
            mode=mode,
            issues=[],
            comparison=comparison,
            copied_files=0,
            copied_bytes=sum(
                int(item.get("size") or 0)
                for item in current_source["files"]
                if item["path"] in source_only
            ),
            recovered_transactions=recovered_transactions,
        )
        save_json_atomic(report, report_path)
        return report

    source_files = {item["path"]: item for item in current_source["files"]}
    transaction = staging_root / uuid.uuid4().hex
    payload_root = transaction / "payload"
    transaction.mkdir(parents=True, exist_ok=False)
    entries = [
        {
            "path": relative,
            "size": source_files[relative]["size"],
            "sha256": source_files[relative]["sha256"],
        }
        for relative in source_only
    ]
    journal = {
        "schema_version": "1.0",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "state": "staging",
        "source_inventory_sha256": current_source["inventory_sha256"],
        "target_inventory_sha256": current_target["inventory_sha256"],
        "files": entries,
    }
    save_json_atomic(journal, transaction / "transaction.json")
    committed: list[tuple[Path, Path]] = []
    created_directories: list[Path] = []
    copied_bytes = 0
    issues: list[dict[str, Any]] = []
    try:
        for entry in entries:
            relative = entry["path"]
            source = _safe_workspace_member(source_root, relative)
            target = _safe_workspace_member(target_root, relative)
            staged = _safe_workspace_member(payload_root, relative)
            if target.exists() or is_link_or_reparse(target):
                raise FileExistsError(f"目标已存在，拒绝覆盖: {relative}")
            if _has_symlink_parent(target, target_root):
                raise ValueError(f"目标父目录包含符号链接，拒绝写入: {relative}")
            if not source.is_file() or is_link_or_reparse(source):
                raise ValueError(f"源文件不可验证: {relative}")
            if source.stat().st_size != entry["size"] or _sha256(source) != entry["sha256"]:
                raise ValueError(f"源文件在复制前发生变化: {relative}")
            staged.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, staged)
            if staged.stat().st_size != entry["size"] or _sha256(staged) != entry["sha256"]:
                raise OSError(f"staging 回读校验失败: {relative}")
            copied_bytes += entry["size"]

        target_still_matches, _ = _manifest_matches_current(target_root, current_target)
        source_still_matches, _ = _manifest_matches_current(source_root, current_source)
        if not source_still_matches or not target_still_matches:
            raise ValueError("提交前源或目标 Workspace 已变化，拒绝提交")
        journal["state"] = "committing"
        save_json_atomic(journal, transaction / "transaction.json")
        for entry in entries:
            relative = entry["path"]
            staged = _safe_workspace_member(payload_root, relative)
            target = _safe_workspace_member(target_root, relative)
            if target.exists() or is_link_or_reparse(target):
                raise FileExistsError(f"提交时目标已存在，拒绝覆盖: {relative}")
            missing: list[Path] = []
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
            current_target["device_id"],
            scopes=current_target["scopes"],
            max_file_mb=int(current_target.get("max_file_mb") or 512),
        )
        receipt = build_sync_receipt(current_source, final_target)
        if receipt["status"] != "verified":
            raise OSError("提交后目标库存与源库存不一致，开始回滚")
        journal["state"] = "verified"
        save_json_atomic(journal, transaction / "transaction.json")
        shutil.rmtree(transaction)
        try:
            staging_root.rmdir()
        except OSError:
            pass
        report = _handoff_report(
            source_root=source_root,
            target_root=target_root,
            source_manifest=source_manifest,
            target_manifest=target_manifest,
            status="verified",
            mode=mode,
            issues=[],
            comparison=comparison,
            copied_files=len(entries),
            copied_bytes=copied_bytes,
            receipt=receipt,
            recovered_transactions=recovered_transactions,
        )
    except (OSError, ValueError) as exc:
        for target, staged in reversed(committed):
            if target.is_file() and not staged.exists():
                staged.parent.mkdir(parents=True, exist_ok=True)
                os.replace(target, staged)
        for directory in reversed(created_directories):
            try:
                directory.rmdir()
            except OSError:
                pass
        issues.append({"code": "HANDOFF_APPLY_FAILED", "message": str(exc)})
        shutil.rmtree(transaction, ignore_errors=True)
        try:
            staging_root.rmdir()
        except OSError:
            pass
        report = _handoff_report(
            source_root=source_root,
            target_root=target_root,
            source_manifest=source_manifest,
            target_manifest=target_manifest,
            status="failed",
            mode=mode,
            issues=issues,
            comparison=comparison,
            copied_files=0,
            copied_bytes=0,
            recovered_transactions=recovered_transactions,
        )
    save_json_atomic(report, report_path)
    return report
