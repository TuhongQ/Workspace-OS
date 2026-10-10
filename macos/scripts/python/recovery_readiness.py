"""Build an evidence-based recovery readiness and 3-2-1 coverage report."""
from __future__ import annotations

import hashlib
import json
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def _read_json(path: Path) -> dict[str, Any] | None:
    try:
        value = json.loads(path.read_text(encoding="utf-8-sig"))
        return value if isinstance(value, dict) else None
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return None


def _timestamp(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return parsed.replace(tzinfo=timezone.utc) if parsed.tzinfo is None else parsed
    except ValueError:
        return None


def _age_hours(value: str | None, now: datetime) -> float | None:
    parsed = _timestamp(value)
    return None if parsed is None else max(0.0, (now - parsed.astimezone(timezone.utc)).total_seconds() / 3600)


def _sha256(path: Path) -> str | None:
    try:
        digest = hashlib.sha256()
        with path.open("rb") as stream:
            for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(chunk)
        return digest.hexdigest()
    except OSError:
        return None


def _latest_drill(workspace: Path) -> tuple[Path | None, dict[str, Any] | None]:
    root = workspace / "08_Indexes" / "RecoveryDrills"
    candidates: list[tuple[datetime, Path, dict[str, Any]]] = []
    if root.is_dir():
        for path in root.glob("*.json"):
            report = _read_json(path)
            if (report or {}).get("scope") not in {"full", "project", "file", "canary"}:
                continue
            performed = _timestamp((report or {}).get("performed_at"))
            if report and performed:
                candidates.append((performed, path, report))
    if not candidates:
        return None, None
    _, path, report = max(candidates, key=lambda item: item[0])
    return path, report


def _baseline_evidence(snapshots: Path) -> dict[str, Any] | None:
    candidates: list[tuple[datetime, Path, dict[str, Any]]] = []
    if snapshots.is_dir():
        for path in snapshots.iterdir():
            if not path.is_dir() or path.name.startswith(".") or path.name == "_WorkspaceOS_Trash":
                continue
            manifest = _read_json(path / "WORKSPACE-SNAPSHOT-MANIFEST.json")
            created = _timestamp((manifest or {}).get("created_at"))
            if manifest and created and manifest.get("pinned") and not manifest.get("exclusions"):
                candidates.append((created, path, manifest))
    if not candidates:
        return None
    _, path, manifest = max(candidates, key=lambda item: item[0])
    return {
        "snapshot": str(path),
        "created_at": manifest.get("created_at"),
        "file_count": manifest.get("file_count"),
        "total_bytes": manifest.get("total_bytes"),
        "pinned": True,
    }


def build_recovery_readiness(
    workspace: str | Path,
    snapshots: str | Path,
    *,
    restic_executable: str | Path | None = None,
    rpo_hours: int = 26,
    drill_max_days: int = 90,
    verification_max_days: int = 8,
    drill_report: str | Path | None = None,
    recovery_kit_report: str | Path | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    root = Path(workspace).expanduser().resolve()
    snapshot_root = Path(snapshots).expanduser().resolve()
    if rpo_hours < 1 or drill_max_days < 1 or verification_max_days < 1:
        raise ValueError("Recovery readiness objectives must be positive.")
    current = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    findings: list[dict[str, Any]] = []

    def add(severity: str, code: str, message: str, **details: Any) -> None:
        findings.append({"severity": severity, "code": code, "message": message, **details})

    status_path = root / "07_Admin" / "WorkspaceOS" / "backup-status.json"
    status = _read_json(status_path)
    latest_snapshot = Path(status.get("last_snapshot", "")) if status else None
    snapshot_age = _age_hours((status or {}).get("last_snapshot_at"), current)
    snapshot_verified = bool(status and status.get("verified") and latest_snapshot and latest_snapshot.is_dir())
    if not snapshot_verified:
        add("CRITICAL", "VERIFIED_SNAPSHOT_MISSING", "没有可确认存在的已验证本地快照", path=str(status_path))
    elif snapshot_age is None or snapshot_age > rpo_hours:
        add(
            "ERROR",
            "SNAPSHOT_RPO_BREACH",
            f"最近快照超过 {rpo_hours} 小时恢复点目标",
            age_hours=snapshot_age,
            target_hours=rpo_hours,
        )

    verification_path = root / "08_Indexes" / "BackupVerification" / "latest-snapshot-verification.json"
    verification = _read_json(verification_path)
    verification_age = _age_hours((verification or {}).get("checked_at"), current)
    verification_matches_latest = bool(
        verification
        and latest_snapshot
        and Path(str(verification.get("snapshot", ""))).resolve() == latest_snapshot.resolve()
    )
    current_manifest_hash = (
        _sha256(latest_snapshot / "WORKSPACE-SNAPSHOT-MANIFEST.json")
        if latest_snapshot and latest_snapshot.is_dir()
        else None
    )
    verification_manifest_matches = bool(
        current_manifest_hash
        and verification
        and verification.get("manifest_sha256") == current_manifest_hash
    )
    verification_fresh = bool(
        verification_age is not None and verification_age <= verification_max_days * 24
    )
    verification_valid = bool(
        verification
        and verification.get("valid")
        and verification_matches_latest
        and verification_manifest_matches
        and verification_fresh
    )
    source_consistency_verified = bool(
        verification
        and verification.get("source_consistency_verified") is True
    )
    trusted_snapshot = bool(snapshot_verified and verification_valid)
    if not verification or not verification.get("valid") or not verification_matches_latest:
        add(
            "CRITICAL",
            "SNAPSHOT_VERIFICATION_FAILED",
            "最近快照完整性校验证据缺失、失败或与当前快照不匹配",
            path=str(verification_path),
        )
    elif not verification_manifest_matches:
        add(
            "CRITICAL",
            "SNAPSHOT_MANIFEST_DRIFT",
            "当前快照清单与最近一次完整验证证据不一致，不能继续信任该恢复点",
            path=str(latest_snapshot / "WORKSPACE-SNAPSHOT-MANIFEST.json"),
        )
    elif not verification_fresh:
        add(
            "ERROR",
            "SNAPSHOT_VERIFICATION_STALE",
            f"快照完整验证超过 {verification_max_days} 天，恢复点可信度已过期",
            age_hours=verification_age,
            target_days=verification_max_days,
        )
    if verification_valid and not source_consistency_verified:
        add(
            "WARNING",
            "SNAPSHOT_SOURCE_CONSISTENCY_UNPROVEN",
            "最新快照可完整读取，但没有证明复制期间源 Workspace 保持稳定",
            path=str(verification_path),
        )

    if drill_report:
        drill_path = Path(drill_report).expanduser().resolve()
        drill = _read_json(drill_path)
    else:
        drill_path, drill = _latest_drill(root)
    drill_age = _age_hours((drill or {}).get("performed_at"), current)
    drill_snapshot_matches = bool(
        drill
        and latest_snapshot
        and Path(str(drill.get("snapshot", ""))).resolve() == latest_snapshot.resolve()
    )
    drill_manifest_matches = bool(
        drill
        and current_manifest_hash
        and drill.get("snapshot_manifest_sha256") == current_manifest_hash
    )
    drill_passed = bool(
        drill
        and drill.get("result") == "passed"
        and drill_snapshot_matches
        and drill_manifest_matches
    )
    if not drill or drill.get("result") != "passed":
        add("ERROR", "RESTORE_DRILL_MISSING", "没有通过的隔离恢复演练证据")
    elif not drill_snapshot_matches:
        add(
            "ERROR",
            "RESTORE_DRILL_SNAPSHOT_MISMATCH",
            "最近恢复演练并非针对当前最新快照，不能证明当前恢复点可用",
        )
    elif not drill_manifest_matches:
        add(
            "ERROR",
            "RESTORE_DRILL_MANIFEST_MISMATCH",
            "恢复演练绑定的快照清单与当前清单不一致",
        )
    elif drill_age is None or drill_age > drill_max_days * 24:
        add(
            "WARNING",
            "RESTORE_DRILL_STALE",
            f"恢复演练超过 {drill_max_days} 天未执行",
            age_hours=drill_age,
            target_days=drill_max_days,
        )

    baseline = _baseline_evidence(snapshot_root)
    if not baseline:
        add("WARNING", "PINNED_BASELINE_MISSING", "缺少未排除内容且已固定的完整基线快照")

    kit_report_path = (
        Path(recovery_kit_report).expanduser().resolve()
        if recovery_kit_report
        else root / "08_Indexes" / "Recovery" / "latest-recovery-kit.json"
    )
    kit_report = _read_json(kit_report_path)
    kit_checked_at = ((kit_report or {}).get("verification") or {}).get("checked_at")
    kit_age = _age_hours(kit_checked_at, current)
    kit_valid = bool(
        kit_report
        and kit_report.get("status") in {"created", "existing_verified"}
        and ((kit_report.get("verification") or {}).get("valid"))
        and Path(str(kit_report.get("archive", ""))).is_file()
    )
    if not kit_valid:
        add("WARNING", "RECOVERY_KIT_MISSING", "便携恢复工具包缺失、不可读或未通过校验", path=str(kit_report_path))
    elif kit_age is None or kit_age > 24 * 30:
        add("WARNING", "RECOVERY_KIT_STALE", "便携恢复工具包超过 30 天未更新", age_hours=kit_age)

    same_volume = bool(root.drive and snapshot_root.drive and root.drive.lower() == snapshot_root.drive.lower())
    topology_path = root / "07_Admin" / "WorkspaceOS" / "backup-topology.json"
    topology = _read_json(topology_path)
    legacy_distinct_media = bool(
        not same_volume and (topology or {}).get("local_snapshot_distinct_physical_media")
    )
    export_path = root / "08_Indexes" / "Recovery" / "snapshot-export.json"
    export = _read_json(export_path)
    export_age = _age_hours((export or {}).get("exported_at"), current)
    export_matches_latest = bool(
        export
        and latest_snapshot
        and Path(str(export.get("source_snapshot", ""))).resolve() == latest_snapshot.resolve()
    )
    source_manifest_hash = current_manifest_hash
    export_manifest_matches = bool(
        source_manifest_hash
        and export
        and export.get("source_manifest_sha256") == source_manifest_hash
    )
    external_export_valid = bool(
        export
        and export.get("status") in {"exported", "existing-verified"}
        and export.get("source_verified")
        and export.get("target_verified")
        and export.get("eligible_for_distinct_media")
        and export.get("receipt")
        and export.get("receipt_id")
        and isinstance(export.get("checked_files"), int)
        and export.get("checked_files") > 0
        and export.get("overwritten_files") == 0
        and export.get("deleted_files") == 0
        and export_matches_latest
        and export_manifest_matches
    )
    distinct_media = bool(external_export_valid or legacy_distinct_media)
    if external_export_valid:
        pass
    elif export and not export_matches_latest:
        add(
            "WARNING",
            "EXTERNAL_SNAPSHOT_STALE",
            "独立介质导出收据未对应当前最新快照",
            report=str(export_path),
        )
    elif same_volume:
        add("WARNING", "SNAPSHOT_SAME_VOLUME", "Workspace 与本地快照位于同一卷，不能抵御整盘故障")
    elif not distinct_media:
        add(
            "WARNING",
            "SNAPSHOT_MEDIA_UNCONFIRMED",
            "快照路径位于不同卷，但尚无独立物理介质确认",
            marker=str(topology_path),
        )

    restic_path = Path(restic_executable).expanduser() if restic_executable else root / "07_Admin" / "WorkspaceOS" / "tools" / "restic.exe"
    restic_installed = restic_path.is_file()
    restic_command = shutil.which("restic")
    try:
        restic_scope = (
            "workspace-bundled"
            if restic_installed and restic_path.resolve().is_relative_to(root)
            else "external-or-explicit"
        )
    except (OSError, ValueError):
        restic_scope = "external-or-explicit"
    repository_marker = root / "07_Admin" / "WorkspaceOS" / "restic-repository.json"
    repository = _read_json(repository_marker)
    offsite_encrypted = bool(
        repository
        and repository.get("initialized")
        and repository.get("encrypted")
        and repository.get("offsite")
        and repository.get("last_check_ok")
    )
    if not offsite_encrypted:
        add(
            "WARNING",
            "OFFSITE_ENCRYPTED_BACKUP_MISSING",
            "尚无经过完整性检查的加密异机备份，当前不满足 3-2-1",
            restic_installed=restic_installed,
            restic_command_available=bool(restic_command),
            restic_scope=restic_scope,
            marker=str(repository_marker),
        )

    score = (
        (25 if snapshot_verified and snapshot_age is not None and snapshot_age <= rpo_hours else 0)
        + (15 if verification_valid else 0)
        + (20 if drill_passed and drill_age is not None and drill_age <= drill_max_days * 24 else 0)
        + (15 if distinct_media else 0)
        + (20 if offsite_encrypted else 0)
        + (5 if baseline else 0)
    )
    highest = max(
        ({"INFO": 0, "WARNING": 1, "ERROR": 2, "CRITICAL": 3}[item["severity"]] for item in findings),
        default=0,
    )
    readiness = "unprotected" if highest >= 3 else "degraded" if findings else "ready"
    return {
        "schema_version": "1.5",
        "generated_at": current.isoformat(),
        "workspace": str(root),
        "snapshot_root": str(snapshot_root),
        "status": readiness,
        "score": score,
        "objectives": {
            "rpo_hours": rpo_hours,
            "restore_drill_max_days": drill_max_days,
            "verification_max_days": verification_max_days,
        },
        "coverage": {
            "confirmed_copies": 3 if trusted_snapshot and external_export_valid else 2 if trusted_snapshot else 1,
            "confirmed_media": 2 if distinct_media else 1,
            "confirmed_offsite": 1 if offsite_encrypted else 0,
            "meets_3_2_1": bool(trusted_snapshot and distinct_media and offsite_encrypted),
        },
        "evidence": {
            "latest_snapshot": str(latest_snapshot) if latest_snapshot else None,
            "snapshot_age_hours": round(snapshot_age, 2) if snapshot_age is not None else None,
            "snapshot_verified": snapshot_verified,
            "snapshot_trusted": trusted_snapshot,
            "verification_report": str(verification_path),
            "verification_valid": verification_valid,
            "verification_matches_latest": verification_matches_latest,
            "verification_manifest_matches": verification_manifest_matches,
            "source_consistency_verified": source_consistency_verified,
            "verification_age_days": (
                round(verification_age / 24, 2) if verification_age is not None else None
            ),
            "current_snapshot_manifest_sha256": current_manifest_hash,
            "restore_drill_report": str(drill_path) if drill_path else None,
            "restore_drill_age_days": round(drill_age / 24, 2) if drill_age is not None else None,
            "restore_drill_passed": drill_passed,
            "restore_drill_snapshot_matches": drill_snapshot_matches,
            "restore_drill_manifest_matches": drill_manifest_matches,
            "restore_drill_scope": (drill or {}).get("scope"),
            "restore_drill_checked_files": (drill or {}).get("checked_files"),
            "restore_drill_checked_bytes": (drill or {}).get("checked_bytes"),
            "restore_drill_rto_seconds": (drill or {}).get("rto_observed_seconds"),
            "restore_drill_temporary_content_removed": (drill or {}).get("temporary_content_removed"),
            "pinned_full_baseline": baseline,
            "recovery_kit_report": str(kit_report_path),
            "recovery_kit_valid": kit_valid,
            "recovery_kit_age_days": round(kit_age / 24, 2) if kit_age is not None else None,
            "restic_installed": restic_installed,
            "restic_command_available": bool(restic_command),
            "restic_command": restic_command,
            "restic_scope": restic_scope,
            "restic_repository_marker": str(repository_marker),
            "backup_topology_marker": str(topology_path),
            "snapshot_export_report": str(export_path),
            "snapshot_export_valid": external_export_valid,
            "snapshot_export_age_days": round(export_age / 24, 2) if export_age is not None else None,
            "snapshot_export_matches_latest": export_matches_latest,
            "snapshot_export_manifest_matches": export_manifest_matches,
            "offsite_encrypted_backup": offsite_encrypted,
        },
        "findings": findings,
    }


def save_recovery_readiness(report: dict[str, Any], output: str | Path) -> tuple[Path, Path]:
    json_path = Path(output)
    md_path = json_path.with_suffix(".md")
    json_path.parent.mkdir(parents=True, exist_ok=True)
    json_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    coverage = report["coverage"]
    lines = [
        "# Workspace OS 恢复就绪度",
        "",
        f"- 状态：**{report['status'].upper()}**",
        f"- 证据分数：**{report['score']} / 100**",
        f"- 3-2-1：{'满足' if coverage['meets_3_2_1'] else '尚未满足'}",
        f"- 已确认副本 / 介质 / 异地：{coverage['confirmed_copies']} / {coverage['confirmed_media']} / {coverage['confirmed_offsite']}",
        "",
        "## 发现",
        "",
    ]
    if report["findings"]:
        lines.extend(f"- **{item['severity']}** `{item['code']}` — {item['message']}" for item in report["findings"])
    else:
        lines.append("- 无恢复就绪度缺口。")
    md_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return json_path, md_path
