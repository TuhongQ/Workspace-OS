"""Verified, no-overwrite export of Workspace snapshots to independent media."""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from backup import MANIFEST_NAME, verify_snapshot

MEDIA_MARKER = ".workspace-os-backup-media.json"
TRANSACTION_DIRECTORY = ".workspace-os-transactions"
SNAPSHOT_DIRECTORY = "WorkspaceOS-Snapshots"
RECEIPT_DIRECTORY = "WorkspaceOS-Receipts"


def _resolved(path: str | Path) -> Path:
    return Path(path).expanduser().resolve(strict=False)


def _is_within(path: Path, parent: Path) -> bool:
    try:
        path.relative_to(parent)
        return True
    except ValueError:
        return False


def _validate_non_root(path: Path, label: str) -> None:
    if path == Path(path.anchor):
        raise ValueError(f"拒绝把文件系统根目录作为{label}；请创建专用子目录")


def _atomic_json(path: Path, value: dict[str, Any]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(temporary, path)
    return path


def _read_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"JSON 不可读: {path}") from exc
    if not isinstance(value, dict):
        raise ValueError(f"JSON 根节点必须是对象: {path}")
    return value


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _volume_identity(path: Path) -> str:
    resolved = _resolved(path)
    if resolved.drive:
        return f"drive:{resolved.drive.casefold()}"
    probe = resolved
    while not probe.exists() and probe != probe.parent:
        probe = probe.parent
    try:
        return f"device:{probe.stat().st_dev}"
    except OSError:
        return f"anchor:{resolved.anchor.casefold()}"


def _load_media_marker(media_root: Path) -> dict[str, Any]:
    marker_path = media_root / MEDIA_MARKER
    marker = _read_json(marker_path)
    if marker.get("schema_version") != "1.0":
        raise ValueError(f"备份介质标记版本无效: {marker_path}")
    if not marker.get("media_id") or not marker.get("declared_distinct_physical_media"):
        raise ValueError(f"备份介质尚未确认物理独立性: {marker_path}")
    return marker


def initialize_backup_media(
    destination: str | Path,
    label: str,
    *,
    confirm_distinct_physical_media: bool = False,
    apply: bool = False,
) -> dict[str, Any]:
    """Create a non-destructive identity marker in a dedicated media directory."""
    root = _resolved(destination)
    _validate_non_root(root, "备份介质目录")
    clean_label = label.strip()
    if not clean_label:
        raise ValueError("备份介质标签不能为空")
    marker_path = root / MEDIA_MARKER
    result: dict[str, Any] = {
        "schema_version": "1.0",
        "mode": "apply" if apply else "dry-run",
        "status": "planned",
        "destination": str(root),
        "marker": str(marker_path),
        "label": clean_label,
        "declared_distinct_physical_media": bool(confirm_distinct_physical_media),
    }
    if marker_path.exists():
        raise FileExistsError(f"介质标记已存在，拒绝覆盖: {marker_path}")
    if not confirm_distinct_physical_media:
        result.update(
            status="blocked",
            issues=[
                {
                    "code": "PHYSICAL_MEDIA_CONFIRMATION_REQUIRED",
                    "message": "必须人工确认目标是独立物理设备，而非同盘分区或普通目录",
                }
            ],
        )
        return result
    if not apply:
        return result
    root.mkdir(parents=True, exist_ok=True)
    marker = {
        "schema_version": "1.0",
        "media_id": uuid.uuid4().hex,
        "label": clean_label,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "declared_distinct_physical_media": True,
        "note": "This marker does not format, encrypt, or delete content on the media.",
    }
    _atomic_json(marker_path, marker)
    result.update(status="initialized", media_id=marker["media_id"], created_at=marker["created_at"])
    return result


def _manifest_digest(snapshot: Path) -> str:
    manifest = snapshot / MANIFEST_NAME
    if not manifest.is_file():
        raise ValueError(f"快照缺少 {MANIFEST_NAME}: {snapshot}")
    return _sha256(manifest)


def _safe_transaction_path(media_root: Path, value: str, label: str) -> Path:
    candidate = _resolved(value)
    if not _is_within(candidate, media_root):
        raise ValueError(f"事务中的{label}越出备份介质目录")
    return candidate


def _recover_interrupted_exports(media_root: Path) -> list[dict[str, Any]]:
    transaction_root = media_root / TRANSACTION_DIRECTORY
    recovered: list[dict[str, Any]] = []
    if not transaction_root.is_dir():
        return recovered
    for journal_path in sorted(transaction_root.glob("*.json")):
        journal = _read_json(journal_path)
        staging = _safe_transaction_path(media_root, str(journal.get("staging", "")), "staging")
        target = _safe_transaction_path(media_root, str(journal.get("target", "")), "target")
        batch = (
            media_root
            / "_WorkspaceOS_Trash"
            / "InterruptedSnapshotExports"
            / f"{datetime.now().strftime('%Y%m%d-%H%M%S')}-{uuid.uuid4().hex[:8]}"
        )
        batch.mkdir(parents=True, exist_ok=False)
        action = "journal-archived"
        if staging.exists():
            shutil.move(str(staging), str(batch / staging.name))
            action = "partial-moved-to-recoverable-trash"
        shutil.move(str(journal_path), str(batch / journal_path.name))
        recovered.append(
            {
                "transaction_id": journal.get("transaction_id"),
                "action": action,
                "target_exists": target.exists(),
                "trash": str(batch),
            }
        )
    return recovered


def _write_export_receipt(
    *,
    media_root: Path,
    marker: dict[str, Any],
    source: Path,
    target: Path,
    source_manifest_sha256: str,
    source_volume: str,
    workspace_volume: str,
    media_volume: str,
    distinct_volume: bool,
    eligible: bool,
    checked_files: int,
) -> tuple[dict[str, Any], Path]:
    exported_at = datetime.now(timezone.utc).isoformat()
    receipt = {
        "schema_version": "1.0",
        "receipt_id": hashlib.sha256(
            f"{marker['media_id']}:{source_manifest_sha256}:{target}".encode("utf-8")
        ).hexdigest()[:24],
        "exported_at": exported_at,
        "source_snapshot": str(source),
        "target_snapshot": str(target),
        "source_manifest_sha256": source_manifest_sha256,
        "media_id": marker["media_id"],
        "media_label": marker.get("label"),
        "source_volume": source_volume,
        "workspace_volume": workspace_volume,
        "media_volume": media_volume,
        "distinct_volume": distinct_volume,
        "declared_distinct_physical_media": marker["declared_distinct_physical_media"],
        "eligible_for_distinct_media": eligible,
        "verified": True,
        "checked_files": checked_files,
        "overwritten_files": 0,
        "deleted_files": 0,
    }
    receipt_path = (
        media_root
        / RECEIPT_DIRECTORY
        / f"{source.name}-{source_manifest_sha256[:12]}.json"
    )
    if receipt_path.exists():
        existing = _read_json(receipt_path)
        invariant_fields = (
            "schema_version",
            "receipt_id",
            "source_snapshot",
            "target_snapshot",
            "source_manifest_sha256",
            "media_id",
            "source_volume",
            "workspace_volume",
            "media_volume",
            "distinct_volume",
            "declared_distinct_physical_media",
            "eligible_for_distinct_media",
            "verified",
            "checked_files",
            "overwritten_files",
            "deleted_files",
        )
        if (
            not existing.get("exported_at")
            or any(existing.get(field) != receipt.get(field) for field in invariant_fields)
        ):
            raise FileExistsError(f"介质收据已存在且不匹配，拒绝覆盖: {receipt_path}")
        receipt = existing
    else:
        _atomic_json(receipt_path, receipt)
    return receipt, receipt_path


def export_snapshot_to_media(
    snapshot: str | Path,
    media: str | Path,
    *,
    apply: bool = False,
    output: str | Path | None = None,
    allow_same_volume_for_simulation: bool = False,
    copy_tree: Callable[..., Any] = shutil.copytree,
) -> dict[str, Any]:
    """Verify, stage, verify again, and atomically export a snapshot without overwrite."""
    source = _resolved(snapshot)
    media_root = _resolved(media)
    _validate_non_root(media_root, "备份介质目录")
    if not source.is_dir():
        raise ValueError(f"快照不存在或不是目录: {source}")
    if _is_within(media_root, source) or _is_within(source, media_root):
        raise ValueError("快照源与介质目录不能互相包含")
    marker = _load_media_marker(media_root)
    source_verification = verify_snapshot(source)
    source_manifest_sha256 = _manifest_digest(source)
    source_manifest = _read_json(source / MANIFEST_NAME)
    workspace_source = _resolved(str(source_manifest.get("source", source)))
    source_volume = _volume_identity(source)
    workspace_volume = _volume_identity(workspace_source)
    media_volume = _volume_identity(media_root)
    distinct_volume = media_volume not in {source_volume, workspace_volume}
    target = media_root / SNAPSHOT_DIRECTORY / source.name
    eligible = bool(marker["declared_distinct_physical_media"] and distinct_volume)
    result: dict[str, Any] = {
        "schema_version": "1.0",
        "mode": "apply" if apply else "dry-run",
        "status": "planned",
        "source_snapshot": str(source),
        "target_snapshot": str(target),
        "media_root": str(media_root),
        "media_id": marker["media_id"],
        "media_label": marker.get("label"),
        "source_manifest_sha256": source_manifest_sha256,
        "source_verified": source_verification["valid"],
        "checked_files": source_verification["checked_files"],
        "source_volume": source_volume,
        "workspace_volume": workspace_volume,
        "media_volume": media_volume,
        "distinct_volume": distinct_volume,
        "eligible_for_distinct_media": eligible,
        "recovered_transactions": [],
        "overwritten_files": 0,
        "deleted_files": 0,
    }
    if not source_verification["valid"]:
        result.update(status="blocked", issues=source_verification["issues"])
        return result
    if not distinct_volume and not allow_same_volume_for_simulation:
        result.update(
            status="blocked",
            issues=[
                {
                    "code": "BACKUP_MEDIA_SAME_VOLUME",
                    "message": "目标与 Workspace 或快照源位于同一卷，不能作为独立介质导出",
                }
            ],
        )
        return result
    if not apply:
        if target.exists():
            result.update(status="blocked", issues=[{"code": "TARGET_EXISTS", "message": "目标快照已存在，拒绝覆盖"}])
        return result

    media_root.mkdir(parents=True, exist_ok=True)
    recovered = _recover_interrupted_exports(media_root)
    result["recovered_transactions"] = recovered
    if target.exists():
        existing = verify_snapshot(target)
        if existing["valid"] and _manifest_digest(target) == source_manifest_sha256:
            receipt, receipt_path = _write_export_receipt(
                media_root=media_root,
                marker=marker,
                source=source,
                target=target,
                source_manifest_sha256=source_manifest_sha256,
                source_volume=source_volume,
                workspace_volume=workspace_volume,
                media_volume=media_volume,
                distinct_volume=distinct_volume,
                eligible=eligible,
                checked_files=existing["checked_files"],
            )
            result.update(
                status="existing-verified",
                target_verified=True,
                exported_at=receipt["exported_at"],
                receipt=str(receipt_path),
                receipt_id=receipt["receipt_id"],
            )
            if output:
                result["output"] = str(_atomic_json(_resolved(output), result))
            return result
        raise FileExistsError(f"目标快照已存在且不匹配，拒绝覆盖: {target}")

    transaction_id = uuid.uuid4().hex
    target.parent.mkdir(parents=True, exist_ok=True)
    staging = target.parent / f".{source.name}.partial-{transaction_id}"
    journal_path = media_root / TRANSACTION_DIRECTORY / f"{transaction_id}.json"
    journal = {
        "schema_version": "1.0",
        "transaction_id": transaction_id,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "phase": "copying",
        "source": str(source),
        "staging": str(staging),
        "target": str(target),
        "source_manifest_sha256": source_manifest_sha256,
    }
    _atomic_json(journal_path, journal)
    try:
        copy_tree(source, staging, symlinks=True)
        journal["phase"] = "staging-copied"
        _atomic_json(journal_path, journal)
        staging_verification = verify_snapshot(staging)
        if not staging_verification["valid"] or _manifest_digest(staging) != source_manifest_sha256:
            raise OSError(f"介质 staging 校验失败: {staging_verification['issues'][:3]}")
        journal["phase"] = "staging-verified"
        _atomic_json(journal_path, journal)
        os.replace(staging, target)
        journal["phase"] = "committed"
        _atomic_json(journal_path, journal)
        target_verification = verify_snapshot(target)
        if not target_verification["valid"] or _manifest_digest(target) != source_manifest_sha256:
            raise OSError(f"介质提交后校验失败: {target_verification['issues'][:3]}")
        receipt, receipt_path = _write_export_receipt(
            media_root=media_root,
            marker=marker,
            source=source,
            target=target,
            source_manifest_sha256=source_manifest_sha256,
            source_volume=source_volume,
            workspace_volume=workspace_volume,
            media_volume=media_volume,
            distinct_volume=distinct_volume,
            eligible=eligible,
            checked_files=target_verification["checked_files"],
        )
        journal_path.unlink(missing_ok=True)
    except Exception:
        # Leave the machine-owned journal and partial directory intact. The next
        # apply run moves both into recoverable trash before retrying.
        raise

    result.update(
        status="exported",
        exported_at=receipt["exported_at"],
        target_verified=True,
        checked_files=target_verification["checked_files"],
        receipt=str(receipt_path),
        receipt_id=receipt["receipt_id"],
    )
    if output:
        result["output"] = str(_atomic_json(_resolved(output), result))
    return result
