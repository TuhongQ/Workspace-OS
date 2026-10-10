#!/usr/bin/env python3
"""Workspace OS 2.0 统一命令行。Python 3.11+，仅依赖标准库。"""
from __future__ import annotations

import argparse
import json
import sys
import uuid
from pathlib import Path

from audit import audit_workspace, write_audit
from alert_center import build_alert_center, save_alert_center
from backup import apply_retention, create_snapshot, restore_snapshot, set_snapshot_pin, verify_snapshot
from backup_media import export_snapshot_to_media, initialize_backup_media
from change_guard import run_change_guard
from device_bundle import export_device_bundle, import_device_bundle, verify_device_bundle
from duplicate_finder import find_duplicates, write_reports
from device_sync import (
    apply_source_only_handoff,
    build_device_manifest,
    build_sync_receipt,
    compare_device_manifests,
    load_device_manifest,
    save_json_atomic,
)
from distribution import build_distribution, verify_distribution
from evidence_chain import append_evidence_record, verify_evidence_chain
from health import save_health, workspace_health
from graph_builder import build_workspace_graph, save_workspace_graph
from index_builder import build_index, save_index
from location_snapshot import build_location_snapshot, save_location_snapshot
from maintenance_audit import audit_maintenance_tasks, save_maintenance_audit
from notification_center import create_notification_outbox
from operations_drill import run_operations_history_drill
from operations_history import append_operations_record, verify_operations_history
from release_builder import build_release, write_manifest
from recovery_readiness import build_recovery_readiness, save_recovery_readiness
from recovery_kit import apply_recovery_kit_retention, build_recovery_kit, verify_recovery_kit
from restore_drill import run_restore_drill
from search_engine import (
    build_search_database,
    check_search_database,
    maintain_search_database,
    search_database,
    search_status,
)
from security_audit import audit_security, save_security_audit
from security_posture import build_security_posture, save_security_posture
from version_detector import scan_latest
from workspace_core import init_workspace, new_project, scan_inbox


def _print(value: object) -> None:
    print(json.dumps(value, ensure_ascii=False, indent=2, default=str))


def parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="workspace-os", description="Workspace OS 2.0：跨平台数字资产工作区管理")
    p.add_argument("--version", action="version", version="Workspace OS 2.0.0")
    sub = p.add_subparsers(dest="command", required=True)
    init = sub.add_parser("init", help="初始化标准 Workspace（默认实际创建；--dry-run 仅预览）")
    init.add_argument("--path", default="Workspace"); init.add_argument("--dry-run", action="store_true")
    new = sub.add_parser("new", help="从模板创建项目")
    new.add_argument("type", choices=["software", "ai", "video", "work"]); new.add_argument("name")
    new.add_argument("--workspace", default="Workspace"); new.add_argument("--dry-run", action="store_true")
    new.add_argument("--space", choices=["work", "personal"], default="work", help="项目空间：work 工作，personal 生活")
    scan = sub.add_parser("scan-inbox", help="生成 Inbox 移动建议；仅 --apply 时移动")
    scan.add_argument("--workspace", default="Workspace"); scan.add_argument("--dry-run", action="store_true")
    scan.add_argument("--apply", action="store_true")
    latest = sub.add_parser("latest", help="识别最新正式版、工作版、审核版")
    latest.add_argument("path")
    audit = sub.add_parser("audit", help="只读审计并输出报告")
    audit.add_argument("--workspace", default="Workspace"); audit.add_argument("--output")
    audit.add_argument("--skip-duplicates", action="store_true")
    index = sub.add_parser("index", help="构建本地 JSON 索引")
    index.add_argument("--workspace", default="Workspace"); index.add_argument("--output"); index.add_argument("--hash", action="store_true")
    dup = sub.add_parser("duplicates", help="按大小和 SHA-256 查找重复文件")
    dup.add_argument("path"); dup.add_argument("--output")
    release = sub.add_parser("release", help="预览或构建正式发布目录")
    release.add_argument("path"); release.add_argument("--destination"); release.add_argument("--release-version", default="unknown")
    release.add_argument("--apply", action="store_true")
    manifest = sub.add_parser("manifest", help="为已有发布目录生成清单和 SHA-256")
    manifest.add_argument("path"); manifest.add_argument("--release-version", default="unknown")
    locations = sub.add_parser("locations", help="生成电脑/NAS 文件位置网页快照")
    locations.add_argument("--computer", default="D:\\Workspace"); locations.add_argument("--nas", default="W:\\")
    locations.add_argument("--output", default="D:\\Workspace\\08_Indexes\\file-locations.html")
    locations.add_argument("--hash-max-mb", type=int, default=256)
    locations.add_argument("--refresh-nas", action="store_true", help="强制实时遍历 NAS；默认复用上次 NAS 元数据以避免 SMB 阻塞")
    locations.add_argument("--nas-cache", help="从指定的本地 JSON 恢复 NAS 元数据缓存")
    locations.add_argument("--refresh-nas-capacity", action="store_true", help="refresh NAS capacity without a full NAS file scan")
    snapshot = sub.add_parser("snapshot", help="预览或创建可校验的 Workspace 本地快照")
    snapshot.add_argument("--workspace", default="Workspace")
    snapshot.add_argument("--destination", required=True, help="快照根目录，例如 D:\\WorkspaceSnapshots")
    snapshot.add_argument("--name", help="可选快照目录名；默认使用 Workspace_时间")
    snapshot.add_argument("--apply", action="store_true", help="实际创建；不指定时仅预览")
    snapshot.add_argument("--exclude-rebuildable-cache", action="store_true", help="显式排除 .vs、node_modules、.venv、*.ipch 等可重建缓存")
    verify = sub.add_parser("verify-snapshot", help="完整校验快照清单、大小和 SHA-256")
    verify.add_argument("path")
    verify.add_argument("--output")
    pin = sub.add_parser("pin-snapshot", help="固定里程碑快照，使其不参与自动淘汰")
    pin.add_argument("path")
    pin.add_argument("--unpin", action="store_true")
    restore = sub.add_parser("restore", help="校验后恢复到全新隔离目录；默认仅预览")
    restore.add_argument("snapshot")
    restore.add_argument("--destination", required=True)
    restore.add_argument("--apply", action="store_true")
    retention = sub.add_parser("retention", help="预览或执行 GFS 快照保留策略")
    retention.add_argument("--destination", required=True)
    retention.add_argument("--hourly", type=int, default=24)
    retention.add_argument("--daily", type=int, default=30)
    retention.add_argument("--weekly", type=int, default=12)
    retention.add_argument("--monthly", type=int, default=12)
    retention.add_argument("--apply", action="store_true", help="淘汰项移入回收区；不永久删除")
    media_init = sub.add_parser("backup-media-init", help="在专用目录创建非破坏性的独立备份介质身份标记")
    media_init.add_argument("--destination", required=True)
    media_init.add_argument("--label", required=True)
    media_init.add_argument(
        "--confirm-distinct-physical-media",
        action="store_true",
        help="人工确认目标是另一块物理设备，而非同盘分区",
    )
    media_init.add_argument("--apply", action="store_true")
    snapshot_export = sub.add_parser("snapshot-export", help="把已验证快照事务式导出到独立介质并签发收据")
    snapshot_export.add_argument("--snapshot", required=True)
    snapshot_export.add_argument("--media", required=True)
    snapshot_export.add_argument("--output")
    snapshot_export.add_argument("--apply", action="store_true")
    snapshot_export.add_argument(
        "--simulation",
        action="store_true",
        help="仅供隔离演练：允许同卷复制，但收据不计入独立介质覆盖",
    )
    kit_retention = sub.add_parser("recovery-kit-retention", help="预览或执行恢复工具包分层保留策略")
    kit_retention.add_argument("--destination", required=True)
    kit_retention.add_argument("--keep-latest", type=int, default=3)
    kit_retention.add_argument("--daily", type=int, default=7)
    kit_retention.add_argument("--weekly", type=int, default=8)
    kit_retention.add_argument("--monthly", type=int, default=6)
    kit_retention.add_argument("--protect-report", action="append", default=[])
    kit_retention.add_argument("--output")
    kit_retention.add_argument("--apply", action="store_true", help="过期成对产物移入回收区；不永久删除")
    device_manifest = sub.add_parser("device-manifest", help="生成隐私最小化的跨设备内容清单")
    device_manifest.add_argument("--workspace", default="Workspace")
    device_manifest.add_argument("--device-id", required=True)
    device_manifest.add_argument("--include", action="append", default=[])
    device_manifest.add_argument("--max-file-mb", type=int, default=512)
    device_manifest.add_argument("--output", required=True)
    device_compare = sub.add_parser("device-compare", help="比较源设备与目标设备清单并生成只读复制门禁")
    device_compare.add_argument("source_manifest")
    device_compare.add_argument("target_manifest")
    device_compare.add_argument("--output", required=True)
    device_receipt = sub.add_parser("device-receipt", help="仅在两端内容完全一致时签发切换主设备收据")
    device_receipt.add_argument("source_manifest")
    device_receipt.add_argument("target_manifest")
    device_receipt.add_argument("--output", required=True)
    device_apply = sub.add_parser("device-apply", help="只复制 source-only 文件；提交前复扫并支持异常回滚")
    device_apply.add_argument("--source-workspace", required=True)
    device_apply.add_argument("--target-workspace", required=True)
    device_apply.add_argument("--source-manifest", required=True)
    device_apply.add_argument("--target-manifest", required=True)
    device_apply.add_argument("--output")
    device_apply.add_argument("--apply", action="store_true")
    bundle_export = sub.add_parser("device-bundle-export", help="生成经过完整校验的离线设备交接包")
    bundle_export.add_argument("--workspace", default="Workspace")
    bundle_export.add_argument("--device-id", required=True)
    bundle_export.add_argument("--destination", required=True)
    bundle_export.add_argument("--include", action="append", default=[])
    bundle_export.add_argument("--max-file-mb", type=int, default=512)
    bundle_export.add_argument("--confirm-protected-transport", action="store_true")
    bundle_export.add_argument("--simulation", action="store_true")
    bundle_export.add_argument("--output")
    bundle_export.add_argument("--apply", action="store_true")
    bundle_verify = sub.add_parser("device-bundle-verify", help="只读校验离线设备交接包")
    bundle_verify.add_argument("archive")
    bundle_import = sub.add_parser("device-bundle-import", help="零覆盖导入离线设备交接包")
    bundle_import.add_argument("archive")
    bundle_import.add_argument("--target-workspace", required=True)
    bundle_import.add_argument("--target-device-id", required=True)
    bundle_import.add_argument("--output")
    bundle_import.add_argument("--apply", action="store_true")
    doctor = sub.add_parser("doctor", help="检查 Workspace、快照、容量、缓存和 NAS 健康状态")
    doctor.add_argument("--workspace", default="Workspace")
    doctor.add_argument("--snapshots")
    doctor.add_argument("--nas")
    doctor.add_argument("--nas-probe", help="由有界外部进程生成的 NAS 健康探测 JSON")
    doctor.add_argument("--backup-max-age-hours", type=int, default=26)
    doctor.add_argument("--output")
    search_build = sub.add_parser("search-build", help="增量构建隐私安全的 SQLite FTS5 搜索索引")
    search_build.add_argument("--workspace", default="Workspace")
    search_build.add_argument("--database")
    search_build.add_argument("--content", action="store_true", help="仅在本机索引非敏感文本内容")
    search_build.add_argument("--max-content-kb", type=int, default=1024)
    search = sub.add_parser("search", help="查询 SQLite 全文搜索索引")
    search.add_argument("query", nargs="?", default="")
    search.add_argument("--database", required=True)
    search.add_argument("--project")
    search.add_argument("--category")
    search.add_argument("--extension")
    search.add_argument("--status")
    search.add_argument("--archive-state")
    search.add_argument("--limit", type=int, default=50)
    search_info = sub.add_parser("search-status", help="查看搜索索引状态")
    search_info.add_argument("--database", required=True)
    search_check = sub.add_parser("search-check", help="只读校验 SQLite、Schema、文档表与 FTS5 一致性")
    search_check.add_argument("--database", required=True)
    search_maintain = sub.add_parser("search-maintain", help="在候选库更新并校验后原子切换，保留上一代回退")
    search_maintain.add_argument("--workspace", default="Workspace")
    search_maintain.add_argument("--database")
    search_maintain.add_argument("--content", action="store_true")
    search_maintain.add_argument("--max-content-kb", type=int, default=1024)
    search_maintain.add_argument("--output")
    graph = sub.add_parser("graph-build", help="构建项目、客户分组与 Obsidian 知识关系图")
    graph.add_argument("--workspace", default="Workspace")
    graph.add_argument("--output")
    alerts = sub.add_parser("alerts", help="汇总健康、审计、备份、搜索和关系图告警")
    alerts.add_argument("--workspace", default="Workspace")
    alerts.add_argument("--output")
    readiness = sub.add_parser("recovery-readiness", help="生成恢复就绪度、RPO、演练与 3-2-1 覆盖报告")
    readiness.add_argument("--workspace", default="Workspace")
    readiness.add_argument("--snapshots", required=True)
    readiness.add_argument("--restic-executable")
    readiness.add_argument("--rpo-hours", type=int, default=26)
    readiness.add_argument("--drill-max-days", type=int, default=90)
    readiness.add_argument("--verification-max-days", type=int, default=8)
    readiness.add_argument("--drill-report", help="可选：使用隔离路径中的最新恢复演练报告，不覆盖工作区报告")
    readiness.add_argument("--recovery-kit-report", help="可选：使用隔离路径中的恢复工具包报告，不覆盖工作区报告")
    readiness.add_argument("--output")
    notifications = sub.add_parser("notifications", help="生成去重且不含路径的告警通知发件箱")
    notifications.add_argument("--workspace", default="Workspace")
    notifications.add_argument("--min-severity", choices=["WARNING", "ERROR", "CRITICAL"], default="ERROR")
    notifications.add_argument("--output")
    maintenance = sub.add_parser("maintenance-audit", help="校验 Windows 维护任务的脚本、参数、身份与触发器")
    maintenance.add_argument("--task-report", required=True)
    maintenance.add_argument("--policy", default=str(Path(__file__).resolve().parents[2] / "config" / "maintenance-policy.json"))
    maintenance.add_argument("--repository", default=str(Path(__file__).resolve().parents[2]))
    maintenance.add_argument("--workspace", default="Workspace")
    maintenance.add_argument("--snapshots", required=True)
    maintenance.add_argument("--nas", default="W:\\")
    maintenance.add_argument("--restore-root", default=r"D:\WorkspaceRestoreTests\Automated")
    maintenance.add_argument("--expected-user", required=True)
    maintenance.add_argument("--output")
    operations = sub.add_parser("operations-record", help="追加隐私最小化运行记录并计算滚动 SLO")
    operations.add_argument("--workspace", default="Workspace")
    operations.add_argument("--window-days", type=int, default=30)
    operations.add_argument("--dedupe-minutes", type=int, default=30)
    operations_verify = sub.add_parser("operations-verify", help="校验运行历史哈希链与原子 head")
    operations_verify.add_argument("--workspace", default="Workspace")
    operations_verify.add_argument("--output")
    operations_drill = sub.add_parser(
        "operations-drill",
        help="在隔离目录验证运行趋势、篡改检测与失效后拒绝追加",
    )
    operations_drill.add_argument("--workspace", default="Workspace")
    operations_drill.add_argument("--drill-root", required=True)
    operations_drill.add_argument("--output")
    recovery_kit = sub.add_parser("recovery-kit", help="预览或生成无用户数据的便携恢复工具包")
    recovery_kit.add_argument("--source", default=str(Path(__file__).resolve().parents[2]))
    recovery_kit.add_argument("--destination", required=True)
    recovery_kit.add_argument("--name")
    recovery_kit.add_argument("--version")
    recovery_kit.add_argument("--restic-executable")
    recovery_kit.add_argument("--report")
    recovery_kit.add_argument("--apply", action="store_true")
    recovery_kit_verify = sub.add_parser("recovery-kit-verify", help="校验恢复工具包内部清单与 SHA-256")
    recovery_kit_verify.add_argument("archive")
    distribution = sub.add_parser("distribution", help="预览或生成可校验、无用户数据的 Workspace OS 发行包")
    distribution.add_argument("--source", default=str(Path(__file__).resolve().parents[2]))
    distribution.add_argument("--destination", required=True)
    distribution.add_argument("--version")
    distribution.add_argument("--report")
    distribution.add_argument("--apply", action="store_true")
    distribution_verify = sub.add_parser("distribution-verify", help="校验 Workspace OS 发行包清单与 SHA-256")
    distribution_verify.add_argument("archive")
    guard = sub.add_parser("change-guard", help="检测批量删除、修改与疑似勒索扩展名；异常时冻结基线")
    guard.add_argument("--workspace", default="Workspace")
    guard.add_argument("--baseline")
    guard.add_argument("--output")
    guard.add_argument("--accept", action="store_true", help="人工复核后显式接受当前状态为新基线")
    security_audit = sub.add_parser("security-audit", help="隐私最小化地检查凭据暴露与越界链接")
    security_audit.add_argument("--workspace", default="Workspace")
    security_audit.add_argument("--config")
    security_audit.add_argument("--max-file-kb", type=int, default=2048)
    security_audit.add_argument("--max-findings", type=int, default=500)
    security_audit.add_argument("--output")
    security_posture = sub.add_parser("security-posture", help="根据平台探针证据审计受保护目录 ACL 与磁盘加密")
    security_posture.add_argument("--workspace", default="Workspace")
    security_posture.add_argument("--probe", required=True)
    security_posture.add_argument("--output")
    evidence_append = sub.add_parser("evidence-append", help="将派生控制平面报告的哈希追加到防篡改证据链")
    evidence_append.add_argument("--workspace", default="Workspace")
    evidence_append.add_argument("--event-type", default="control-plane")
    evidence_append.add_argument("--subject", default="daily-maintenance")
    evidence_append.add_argument("--evidence", action="append", default=[])
    evidence_verify = sub.add_parser("evidence-verify", help="校验证据链连续性、内容哈希与可选当前状态")
    evidence_verify.add_argument("--workspace", default="Workspace")
    evidence_verify.add_argument("--verify-current", action="store_true")
    evidence_verify.add_argument("--output")
    restore_drill = sub.add_parser("restore-drill", help="从最新已验证快照执行隔离 canary 恢复与回读哈希")
    restore_drill.add_argument("--workspace", default="Workspace")
    restore_drill.add_argument("--snapshot", required=True)
    restore_drill.add_argument("--restore-root", required=True)
    restore_drill.add_argument("--samples", type=int, default=16)
    restore_drill.add_argument("--max-file-mb", type=int, default=16)
    restore_drill.add_argument("--max-total-mb", type=int, default=128)
    restore_drill.add_argument("--output")
    return p


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    try:
        if args.command == "init": result = init_workspace(args.path, args.dry_run)
        elif args.command == "new": result = new_project(args.type, args.name, args.workspace, args.dry_run, space=args.space)
        elif args.command == "scan-inbox": result = scan_inbox(args.workspace, apply=args.apply)
        elif args.command == "latest": result = scan_latest(args.path)
        elif args.command == "audit":
            result = audit_workspace(args.workspace, check_duplicates=not args.skip_duplicates)
            out = Path(args.output) if args.output else Path(args.workspace) / "08_Indexes" / "Audit"
            paths = write_audit(result, out); result["reports"] = [str(x) for x in paths]
        elif args.command == "index":
            result = build_index(args.workspace, args.hash)
            out = Path(args.output) if args.output else Path(args.workspace) / "08_Indexes" / "workspace-index.json"
            save_index(result, out); result = {"output": str(out), "file_count": result["file_count"]}
        elif args.command == "duplicates":
            result = find_duplicates(args.path)
            if args.output:
                out = Path(args.output); write_reports(result, out.with_suffix(".json"), out.with_suffix(".csv"))
        elif args.command == "release": result = build_release(args.path, args.destination, args.release_version, args.apply)
        elif args.command == "manifest": result = {"files": [str(x) for x in write_manifest(args.path, args.release_version)]}
        elif args.command == "locations":
            previous_path = Path(args.nas_cache) if args.nas_cache else Path(args.output).with_suffix(".json")
            previous = None
            if previous_path.is_file():
                try:
                    previous = json.loads(previous_path.read_text(encoding="utf-8-sig"))
                except (OSError, UnicodeDecodeError, json.JSONDecodeError):
                    previous = None
            snapshot = build_location_snapshot(
                args.computer,
                args.nas,
                args.hash_max_mb,
                previous=previous,
                reuse_previous_nas=not args.refresh_nas,
                refresh_nas_storage=args.refresh_nas_capacity,
            )
            outputs = save_location_snapshot(snapshot, args.output)
            result = {"outputs": [str(x) for x in outputs], "counts": snapshot["counts"], "file_count": len(snapshot["files"])}
        elif args.command == "snapshot":
            result = create_snapshot(
                args.workspace,
                args.destination,
                apply=args.apply,
                snapshot_name=args.name,
                exclude_rebuildable_cache=args.exclude_rebuildable_cache,
            )
        elif args.command == "verify-snapshot":
            result = verify_snapshot(args.path)
            if args.output:
                output = Path(args.output)
                output.parent.mkdir(parents=True, exist_ok=True)
                output.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
                result["output"] = str(output)
        elif args.command == "pin-snapshot":
            result = set_snapshot_pin(args.path, pinned=not args.unpin)
        elif args.command == "restore":
            result = restore_snapshot(args.snapshot, args.destination, apply=args.apply)
        elif args.command == "retention":
            result = apply_retention(args.destination, args.hourly, args.daily, args.weekly, args.monthly, args.apply)
        elif args.command == "backup-media-init":
            result = initialize_backup_media(
                args.destination,
                args.label,
                confirm_distinct_physical_media=args.confirm_distinct_physical_media,
                apply=args.apply,
            )
        elif args.command == "snapshot-export":
            result = export_snapshot_to_media(
                args.snapshot,
                args.media,
                apply=args.apply,
                output=args.output,
                allow_same_volume_for_simulation=args.simulation,
            )
        elif args.command == "recovery-kit-retention":
            result = apply_recovery_kit_retention(
                args.destination,
                keep_latest=args.keep_latest,
                daily=args.daily,
                weekly=args.weekly,
                monthly=args.monthly,
                protect_reports=args.protect_report,
                apply=args.apply,
            )
            if args.output:
                output = Path(args.output)
                output.parent.mkdir(parents=True, exist_ok=True)
                temporary = output.with_name(f".{output.name}.{uuid.uuid4().hex}.tmp")
                temporary.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
                temporary.replace(output)
                result["output"] = str(output)
        elif args.command == "device-manifest":
            result = build_device_manifest(
                args.workspace,
                args.device_id,
                scopes=args.include or None,
                max_file_mb=args.max_file_mb,
            )
            result["output"] = str(save_json_atomic(result, args.output))
        elif args.command == "device-compare":
            result = compare_device_manifests(
                load_device_manifest(args.source_manifest),
                load_device_manifest(args.target_manifest),
            )
            result["output"] = str(save_json_atomic(result, args.output))
        elif args.command == "device-receipt":
            result = build_sync_receipt(
                load_device_manifest(args.source_manifest),
                load_device_manifest(args.target_manifest),
            )
            result["output"] = str(save_json_atomic(result, args.output))
        elif args.command == "device-apply":
            result = apply_source_only_handoff(
                args.source_workspace,
                args.target_workspace,
                args.source_manifest,
                args.target_manifest,
                apply=args.apply,
                output=args.output,
            )
        elif args.command == "device-bundle-export":
            result = export_device_bundle(
                args.workspace,
                args.device_id,
                args.destination,
                scopes=args.include or None,
                max_file_mb=args.max_file_mb,
                confirm_protected_transport=args.confirm_protected_transport,
                simulation=args.simulation,
                apply=args.apply,
                output=args.output,
            )
        elif args.command == "device-bundle-verify":
            result = verify_device_bundle(args.archive)
        elif args.command == "device-bundle-import":
            result = import_device_bundle(
                args.archive,
                args.target_workspace,
                args.target_device_id,
                apply=args.apply,
                output=args.output,
            )
        elif args.command == "doctor":
            nas_probe = None
            if args.nas_probe:
                nas_probe = json.loads(Path(args.nas_probe).read_text(encoding="utf-8-sig"))
            result = workspace_health(
                args.workspace,
                args.snapshots,
                args.nas,
                args.backup_max_age_hours,
                nas_probe,
            )
            if args.output:
                outputs = save_health(result, args.output)
                result["outputs"] = [str(path) for path in outputs]
        elif args.command == "search-build":
            database = Path(args.database) if args.database else Path(args.workspace) / "08_Indexes" / "Search" / "workspace-search.db"
            result = build_search_database(args.workspace, database, args.content, args.max_content_kb)
        elif args.command == "search":
            result = search_database(
                args.database,
                args.query,
                project=args.project,
                category=args.category,
                extension=args.extension,
                status=args.status,
                archive_state=args.archive_state,
                limit=args.limit,
            )
        elif args.command == "search-status":
            result = search_status(args.database)
        elif args.command == "search-check":
            result = check_search_database(args.database)
        elif args.command == "search-maintain":
            database = Path(args.database) if args.database else Path(args.workspace) / "08_Indexes" / "Search" / "workspace-search.db"
            output = Path(args.output) if args.output else Path(args.workspace) / "08_Indexes" / "Search" / "search-status.json"
            result = maintain_search_database(
                args.workspace,
                database,
                include_content=args.content,
                max_content_kb=args.max_content_kb,
                output=output,
            )
        elif args.command == "graph-build":
            graph_data = build_workspace_graph(args.workspace)
            output = Path(args.output) if args.output else Path(args.workspace) / "08_Indexes" / "Graph" / "workspace-graph.json"
            save_workspace_graph(graph_data, output)
            result = {"output": str(output), **graph_data["summary"]}
        elif args.command == "alerts":
            alert_data = build_alert_center(args.workspace)
            output = Path(args.output) if args.output else Path(args.workspace) / "08_Indexes" / "Alerts" / "control-plane.json"
            outputs = save_alert_center(alert_data, output)
            result = {**alert_data, "outputs": [str(path) for path in outputs]}
        elif args.command == "recovery-readiness":
            readiness_data = build_recovery_readiness(
                args.workspace,
                args.snapshots,
                restic_executable=args.restic_executable,
                rpo_hours=args.rpo_hours,
                drill_max_days=args.drill_max_days,
                verification_max_days=args.verification_max_days,
                drill_report=args.drill_report,
                recovery_kit_report=args.recovery_kit_report,
            )
            output = Path(args.output) if args.output else Path(args.workspace) / "08_Indexes" / "Recovery" / "recovery-readiness.json"
            outputs = save_recovery_readiness(readiness_data, output)
            result = {**readiness_data, "outputs": [str(path) for path in outputs]}
        elif args.command == "notifications":
            output = Path(args.output) if args.output else Path(args.workspace) / "08_Indexes" / "Alerts" / "notification-outbox.json"
            notification_data, output_path = create_notification_outbox(
                args.workspace,
                output,
                min_severity=args.min_severity,
            )
            result = {**notification_data, "output": str(output_path)}
        elif args.command == "maintenance-audit":
            maintenance_report = audit_maintenance_tasks(
                args.task_report,
                args.policy,
                repository=args.repository,
                workspace=args.workspace,
                snapshots=args.snapshots,
                nas=args.nas,
                restore_root=args.restore_root,
                expected_user=args.expected_user,
            )
            output = (
                Path(args.output)
                if args.output
                else Path(args.workspace) / "08_Indexes" / "Health" / "maintenance-audit.json"
            )
            result = {
                **maintenance_report,
                "output": str(save_maintenance_audit(maintenance_report, output)),
            }
        elif args.command == "operations-record":
            result = append_operations_record(
                args.workspace,
                window_days=args.window_days,
                dedupe_minutes=args.dedupe_minutes,
            )
        elif args.command == "operations-verify":
            result = verify_operations_history(
                args.workspace,
                output=args.output,
            )
        elif args.command == "operations-drill":
            result = run_operations_history_drill(
                args.workspace,
                args.drill_root,
                output=args.output,
            )
        elif args.command == "recovery-kit":
            result = build_recovery_kit(
                args.source,
                args.destination,
                version=args.version,
                name=args.name,
                restic_executable=args.restic_executable,
                apply=args.apply,
            )
            if args.report and args.apply:
                report_path = Path(args.report)
                report_path.parent.mkdir(parents=True, exist_ok=True)
                report_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
                result["report"] = str(report_path)
        elif args.command == "recovery-kit-verify":
            result = verify_recovery_kit(args.archive)
        elif args.command == "distribution":
            result = build_distribution(
                args.source,
                args.destination,
                version=args.version,
                apply=args.apply,
            )
            if args.report and args.apply:
                report_path = Path(args.report)
                report_path.parent.mkdir(parents=True, exist_ok=True)
                report_path.write_text(
                    json.dumps(result, ensure_ascii=False, indent=2),
                    encoding="utf-8",
                )
                result["report"] = str(report_path)
        elif args.command == "distribution-verify":
            result = verify_distribution(args.archive)
        elif args.command == "change-guard":
            baseline = Path(args.baseline) if args.baseline else Path(args.workspace) / "08_Indexes" / "Security" / "change-baseline.json"
            output = Path(args.output) if args.output else Path(args.workspace) / "08_Indexes" / "Security" / "change-guard.json"
            guard_report, baseline_path, output_path = run_change_guard(
                args.workspace,
                baseline,
                output,
                accept=args.accept,
            )
            result = {
                **guard_report,
                "baseline": str(baseline_path),
                "output": str(output_path),
            }
        elif args.command == "security-audit":
            output = (
                Path(args.output)
                if args.output
                else Path(args.workspace) / "08_Indexes" / "Security" / "security-audit.json"
            )
            security_report = audit_security(
                args.workspace,
                config_path=args.config,
                max_file_kb=args.max_file_kb,
                max_findings=args.max_findings,
            )
            outputs = save_security_audit(security_report, output)
            result = {
                **security_report,
                "reports": [str(path) for path in outputs],
            }
        elif args.command == "security-posture":
            output = (
                Path(args.output)
                if args.output
                else Path(args.workspace) / "08_Indexes" / "Security" / "security-posture.json"
            )
            posture_report = build_security_posture(args.workspace, args.probe)
            outputs = save_security_posture(posture_report, output)
            result = {
                **posture_report,
                "reports": [str(path) for path in outputs],
            }
        elif args.command == "evidence-append":
            result = append_evidence_record(
                args.workspace,
                event_type=args.event_type,
                subject=args.subject,
                paths=args.evidence or None,
            )
        elif args.command == "evidence-verify":
            result = verify_evidence_chain(
                args.workspace,
                verify_current=args.verify_current,
                output=args.output,
            )
        elif args.command == "restore-drill":
            result = run_restore_drill(
                args.workspace,
                args.snapshot,
                args.restore_root,
                sample_count=args.samples,
                max_file_mb=args.max_file_mb,
                max_total_mb=args.max_total_mb,
                output=args.output,
            )
        else: raise ValueError("未知命令")
        _print(result)
        if args.command == "restore-drill" and result.get("result") != "passed":
            return 2
        if args.command == "device-apply" and result.get("status") in {"blocked", "failed"}:
            return 2
        if args.command == "device-bundle-verify" and not result.get("valid"):
            return 2
        if args.command == "device-bundle-import" and result.get("status") in {"blocked", "failed"}:
            return 2
        if args.command == "operations-record" and result.get("status") == "blocked":
            return 2
        if args.command == "operations-verify" and not result.get("valid"):
            return 2
        if args.command == "operations-drill" and result.get("result") != "passed":
            return 2
        if args.command in {"backup-media-init", "snapshot-export"} and result.get("status") == "blocked":
            return 2
        return 0
    except (OSError, ValueError) as exc:
        print(f"错误：{exc}", file=sys.stderr); return 2


if __name__ == "__main__":
    raise SystemExit(main())
