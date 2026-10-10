"""汇总健康、审计、备份校验、搜索与关系图状态。"""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

SEVERITY_RANK = {"INFO": 0, "WARNING": 1, "ERROR": 2, "CRITICAL": 3}


def _read_json(path: Path) -> dict[str, Any] | None:
    try:
        value = json.loads(path.read_text(encoding="utf-8-sig"))
        return value if isinstance(value, dict) else None
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return None


def _age_hours(timestamp: str | None) -> float | None:
    if not timestamp:
        return None
    try:
        value = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        return (datetime.now(timezone.utc) - value).total_seconds() / 3600
    except ValueError:
        return None


def build_alert_center(workspace: str | Path) -> dict[str, Any]:
    root = Path(workspace).expanduser().resolve()
    indexes = root / "08_Indexes"
    alerts: list[dict[str, Any]] = []

    def add(severity: str, source: str, code: str, message: str, path: str | Path, **details: Any) -> None:
        identity = f"{source}|{code}|{path}"
        alerts.append({
            "id": hashlib.sha256(identity.encode("utf-8")).hexdigest()[:16],
            "severity": severity,
            "source": source,
            "code": code,
            "message": message,
            "path": str(path),
            **details,
        })

    health_path = indexes / "Health" / "workspace-health.json"
    health = _read_json(health_path)
    if not health:
        add("ERROR", "health", "REPORT_MISSING", "健康报告缺失或不可读", health_path)
    else:
        age = _age_hours(health.get("generated_at"))
        if age is None or age > 26:
            add("WARNING", "health", "REPORT_STALE", "健康报告超过 26 小时未更新", health_path, age_hours=age)
        else:
            for item in health.get("findings", []):
                if item.get("severity") in {"WARNING", "ERROR", "CRITICAL"}:
                    add(item["severity"], "health", item.get("code", "UNKNOWN"), item.get("message", ""), item.get("path", health_path))

    audit_path = indexes / "Audit" / "audit-report.json"
    audit = _read_json(audit_path)
    if not audit:
        add("ERROR", "audit", "REPORT_MISSING", "审计报告缺失或不可读", audit_path)
    else:
        age = _age_hours(audit.get("generated_at"))
        if age is None or age > 24 * 8:
            add("WARNING", "audit", "REPORT_STALE", "审计报告超过 8 天未更新", audit_path, age_hours=age)
        # File-level policy findings stay in the audit report. They are useful
        # for an explicit review, but must not make the live dashboard look
        # unavailable or broken.

    verify_path = indexes / "BackupVerification" / "latest-snapshot-verification.json"
    verification = _read_json(verify_path)
    if not verification:
        add("ERROR", "backup", "VERIFICATION_MISSING", "最近快照校验报告缺失或不可读", verify_path)
    else:
        if not verification.get("valid"):
            add("CRITICAL", "backup", "SNAPSHOT_INVALID", "最近快照完整性校验失败", verify_path, issues=verification.get("issues", []))
        age = _age_hours(verification.get("checked_at"))
        if age is None or age > 24 * 8:
            add("WARNING", "backup", "VERIFICATION_STALE", "快照完整性校验超过 8 天未更新", verify_path, age_hours=age)

    search_path = indexes / "Search" / "workspace-search.db"
    search_meta_path = indexes / "Search" / "search-status.json"
    search_meta = _read_json(search_meta_path)
    if not search_meta:
        add("WARNING", "search", "INDEX_STATUS_MISSING", "搜索索引或状态报告缺失", search_meta_path)
    else:
        age = _age_hours(search_meta.get("generated_at"))
        if age is None or age > 26:
            add("WARNING", "search", "INDEX_STALE", "全文搜索索引超过 26 小时未更新", search_path, age_hours=age)
        else:
            if not search_meta.get("available", True):
                add(
                    "ERROR",
                    "search",
                    "INDEX_UNAVAILABLE",
                    "当前搜索索引和上一代回退均不可用",
                    search_meta_path,
                    current_issues=search_meta.get("current_issues", []),
                    last_good_issues=search_meta.get("last_good_issues", []),
                )
            elif search_meta.get("using_fallback"):
                add(
                    "WARNING",
                    "search",
                    "INDEX_FALLBACK_ACTIVE",
                    "当前搜索索引损坏，正在使用已验证的上一代索引",
                    search_meta_path,
                    current_issues=search_meta.get("current_issues", []),
                )
            if search_meta.get("maintenance_issues"):
                add(
                    "WARNING",
                    "search",
                    "INDEX_MAINTENANCE_FAILED",
                    "搜索索引候选库构建失败，已保留现有可用版本",
                    search_meta_path,
                    issues=search_meta.get("maintenance_issues", []),
                )

    graph_path = indexes / "Graph" / "workspace-graph.json"
    graph = _read_json(graph_path)
    if not graph:
        add("WARNING", "graph", "GRAPH_MISSING", "项目关系图缺失或不可读", graph_path)
    else:
        age = _age_hours(graph.get("generated_at"))
        if age is None or age > 26:
            add("WARNING", "graph", "GRAPH_STALE", "项目关系图超过 26 小时未更新", graph_path, age_hours=age)

    publish_path = indexes / "Alerts" / "nas-publish-status.json"
    publish = _read_json(publish_path)
    if publish and not publish.get("success"):
        publish_age = _age_hours(publish.get("generated_at"))
        publish_code = str(publish.get("code") or "NAS_PUBLISH_FAILED")
        publish_message = str(publish.get("message") or "NAS 仪表盘发布失败")
        if publish_age is not None and publish_age > 26:
            publish_code = "NAS_PUBLISH_STATUS_STALE"
            publish_message = "NAS 发布失败状态超过 26 小时，当前结果需要重新发布确认"
        add(
            "WARNING",
            "nas_publish",
            publish_code,
            publish_message,
            publish_path,
            destination=publish.get("destination"),
            exit_code=publish.get("exit_code"),
            age_hours=publish_age,
        )

    tasks_path = indexes / "Health" / "scheduled-tasks.json"
    tasks = _read_json(tasks_path)
    if tasks:
        age = _age_hours(tasks.get("generated_at"))
        if age is None or age > 26:
            add(
                "WARNING",
                "automation",
                "TASK_STATUS_STALE",
                "计划任务状态超过 26 小时未更新",
                tasks_path,
                age_hours=age,
            )
        else:
            for task in tasks.get("tasks", []):
                task_name = str(task.get("name") or "unknown")
                if not task.get("enabled", True):
                    add(
                        "WARNING",
                        "automation",
                        "TASK_DISABLED",
                        f"自动维护任务已禁用：{task_name}",
                        tasks_path,
                        task=task_name,
                    )
                    continue
                result = int(task.get("last_result") or 0)
                if result not in {0, 267009, 267011}:
                    add(
                        "ERROR",
                        "automation",
                        "TASK_LAST_RUN_FAILED",
                        f"自动维护任务上次执行失败：{task_name}（结果码 {result}）",
                        tasks_path,
                        task=task_name,
                        last_result=result,
                        last_run_time=task.get("last_run_time"),
                    )

    maintenance_audit_path = indexes / "Health" / "maintenance-audit.json"
    maintenance_audit = _read_json(maintenance_audit_path)
    if maintenance_audit:
        age = _age_hours(maintenance_audit.get("generated_at"))
        if age is None or age > 26:
            add(
                "WARNING",
                "automation_integrity",
                "MAINTENANCE_AUDIT_STALE",
                "维护任务定义完整性审计超过 26 小时未更新",
                maintenance_audit_path,
                age_hours=age,
            )
        else:
            for item in maintenance_audit.get("findings", []):
                if item.get("severity") in {"WARNING", "ERROR", "CRITICAL"}:
                    add(
                        item["severity"],
                        "automation_integrity",
                        item.get("code", "UNKNOWN"),
                        item.get("message", ""),
                        maintenance_audit_path,
                        task=item.get("task"),
                    )

    operations_status_path = indexes / "Operations" / "operations-history-status.json"
    operations_status = _read_json(operations_status_path)
    if operations_status and not operations_status.get("valid"):
        add(
            "CRITICAL",
            "operations_history",
            "OPERATIONS_HISTORY_INVALID",
            "运维历史哈希链或 head 校验失败，趋势与故障预算不可继续信任",
            operations_status_path,
            issues=operations_status.get("issues", []),
        )
    operations_slo_path = indexes / "Operations" / "operational-slo.json"
    operations_slo = _read_json(operations_slo_path)
    if operations_slo:
        age = _age_hours(operations_slo.get("generated_at"))
        if age is None or age > 26:
            add(
                "WARNING",
                "operations_slo",
                "OPERATIONS_SLO_STALE",
                "运维 SLO 与故障预算超过 26 小时未更新",
                operations_slo_path,
                age_hours=age,
            )
        else:
            for item in operations_slo.get("findings", []):
                if item.get("severity") in {"WARNING", "ERROR", "CRITICAL"}:
                    add(
                        item["severity"],
                        "operations_slo",
                        item.get("code", "UNKNOWN"),
                        item.get("message", ""),
                        operations_slo_path,
                        signal=item.get("signal"),
                    )

    recovery_path = indexes / "Recovery" / "recovery-readiness.json"
    recovery = _read_json(recovery_path)
    if not recovery:
        add("WARNING", "recovery", "READINESS_REPORT_MISSING", "恢复就绪度报告缺失或不可读", recovery_path)
    else:
        age = _age_hours(recovery.get("generated_at"))
        if age is None or age > 26:
            add("WARNING", "recovery", "READINESS_REPORT_STALE", "恢复就绪度超过 26 小时未更新", recovery_path, age_hours=age)
        else:
            for item in recovery.get("findings", []):
                if item.get("severity") in {"WARNING", "ERROR", "CRITICAL"}:
                    add(
                        item["severity"],
                        "recovery",
                        item.get("code", "UNKNOWN"),
                        item.get("message", ""),
                        recovery_path,
                    )

    kit_retention_path = indexes / "Recovery" / "recovery-kit-retention.json"
    kit_retention = _read_json(kit_retention_path)
    if kit_retention:
        orphans = kit_retention.get("orphans", [])
        report_issues = kit_retention.get("report_issues", [])
        if orphans:
            add(
                "WARNING",
                "recovery",
                "RECOVERY_KIT_ORPHANS",
                f"发现 {len(orphans)} 个缺少配套校验文件的恢复包，已保留待人工检查",
                kit_retention_path,
                count=len(orphans),
            )
        if report_issues:
            add(
                "WARNING",
                "recovery",
                "RECOVERY_KIT_PROTECTION_REPORT_INVALID",
                f"有 {len(report_issues)} 份恢复包保护报告不可读，保留策略未依赖这些报告",
                kit_retention_path,
                count=len(report_issues),
            )

    security_path = indexes / "Security" / "change-guard.json"
    security = _read_json(security_path)
    if not security:
        add("WARNING", "security", "CHANGE_GUARD_REPORT_MISSING", "变化哨兵报告缺失或不可读", security_path)
    else:
        age = _age_hours(security.get("generated_at"))
        if age is None or age > 26:
            add("WARNING", "security", "CHANGE_GUARD_STALE", "变化哨兵超过 26 小时未更新", security_path, age_hours=age)
        else:
            for item in security.get("findings", []):
                if item.get("severity") in {"WARNING", "ERROR", "CRITICAL"}:
                    add(
                        item["severity"],
                        "security",
                        item.get("code", "UNKNOWN"),
                        item.get("message", ""),
                        security_path,
                    )

    exposure_path = indexes / "Security" / "security-audit.json"
    exposure = _read_json(exposure_path)
    if not exposure:
        add(
            "WARNING",
            "security_audit",
            "SECURITY_AUDIT_MISSING",
            "敏感凭据与越界链接安全审计缺失或不可读",
            exposure_path,
        )
    else:
        age = _age_hours(exposure.get("generated_at"))
        if age is None or age > 26:
            add(
                "WARNING",
                "security_audit",
                "SECURITY_AUDIT_STALE",
                "敏感凭据与越界链接安全审计超过 26 小时未更新",
                exposure_path,
                age_hours=age,
            )
        else:
            # Potential secrets and filename findings are file-review items,
            # not service outages. Keep the redacted details in the dedicated
            # security report without flooding the operational alert center.
            if exposure.get("summary", {}).get("truncated"):
                add(
                    "ERROR",
                    "security_audit",
                    "SECURITY_AUDIT_TRUNCATED",
                    "安全审计发现项超过报告上限，必须扩大上限后重新检查",
                    exposure_path,
                )

    posture_path = indexes / "Security" / "security-posture.json"
    posture = _read_json(posture_path)
    if not posture:
        add(
            "WARNING",
            "security_posture",
            "SECURITY_POSTURE_MISSING",
            "受保护目录 ACL 与磁盘加密安全态势报告缺失或不可读",
            posture_path,
        )
    else:
        age = _age_hours(posture.get("generated_at"))
        if age is None or age > 26:
            add(
                "WARNING",
                "security_posture",
                "SECURITY_POSTURE_STALE",
                "ACL 与磁盘加密安全态势超过 26 小时未更新",
                posture_path,
                age_hours=age,
            )
        else:
            for item in posture.get("findings", []):
                if item.get("severity") in {"WARNING", "ERROR", "CRITICAL"}:
                    add(
                        item["severity"],
                        "security_posture",
                        item.get("code", "UNKNOWN"),
                        item.get("message", ""),
                        item.get("path", posture_path),
                    )

    device_sync_path = indexes / "Devices" / "device-sync-status.json"
    device_sync = _read_json(device_sync_path)
    if device_sync and device_sync.get("status") == "blocked":
        summary = device_sync.get("summary") or device_sync.get("comparison", {}).get("summary", {})
        add(
            "WARNING",
            "device_sync",
            "DEVICE_HANDOFF_BLOCKED",
            "跨设备交接存在冲突、目标端独有文件或未验证内容，禁止切换主设备",
            device_sync_path,
            conflicts=summary.get("conflicts"),
            target_only=summary.get("target_only"),
            unverified=summary.get("unverified"),
        )
    device_apply_path = indexes / "Devices" / "device-apply-status.json"
    device_apply = _read_json(device_apply_path)
    if device_apply and device_apply.get("status") in {"blocked", "failed"}:
        severity = "ERROR" if device_apply.get("status") == "failed" else "WARNING"
        add(
            severity,
            "device_sync",
            "DEVICE_HANDOFF_APPLY_FAILED" if severity == "ERROR" else "DEVICE_HANDOFF_APPLY_BLOCKED",
            "跨设备事务复制失败或被安全门禁阻断，未切换主设备",
            device_apply_path,
            issues=device_apply.get("issues", []),
            overwritten_files=device_apply.get("overwritten_files"),
            deleted_files=device_apply.get("deleted_files"),
        )
    bundle_import_path = indexes / "Devices" / "device-bundle-import.json"
    bundle_import = _read_json(bundle_import_path)
    if bundle_import and bundle_import.get("status") in {"blocked", "failed"}:
        severity = "ERROR" if bundle_import.get("status") == "failed" else "WARNING"
        add(
            severity,
            "device_bundle",
            "DEVICE_BUNDLE_IMPORT_FAILED" if severity == "ERROR" else "DEVICE_BUNDLE_IMPORT_BLOCKED",
            "离线设备交接包导入失败或被安全门禁阻止，未授权切换主设备",
            bundle_import_path,
            issues=bundle_import.get("issues", []),
            overwritten_files=bundle_import.get("overwritten_files"),
            deleted_files=bundle_import.get("deleted_files"),
        )

    evidence_path = indexes / "Evidence" / "status.json"
    evidence = _read_json(evidence_path)
    if evidence and evidence.get("status") == "invalid":
        add(
            "CRITICAL",
            "evidence",
            "EVIDENCE_CHAIN_INVALID",
            "控制平面证据链校验失败；历史记录可能缺失、损坏或被修改",
            evidence_path,
            record_count=evidence.get("record_count"),
            issues=evidence.get("issues", []),
        )
    elif evidence and evidence.get("status") == "valid":
        age = _age_hours(evidence.get("checked_at"))
        if age is None or age > 26:
            add(
                "WARNING",
                "evidence",
                "EVIDENCE_CHAIN_STALE",
                "控制平面证据链超过 26 小时未校验",
                evidence_path,
                age_hours=age,
            )

    alerts.sort(key=lambda item: (-SEVERITY_RANK[item["severity"]], item["source"], item["code"], item["path"]))
    highest = max((SEVERITY_RANK[item["severity"]] for item in alerts), default=0)
    status = "critical" if highest == 3 else "error" if highest == 2 else "warning" if highest == 1 else "healthy"
    return {
        "schema_version": "1.0",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "workspace": str(root),
        "status": status,
        "summary": {
            level: sum(1 for item in alerts if item["severity"] == level)
            for level in SEVERITY_RANK
        },
        "alerts": alerts,
    }


def save_alert_center(report: dict[str, Any], output: str | Path) -> tuple[Path, Path]:
    json_path = Path(output)
    md_path = json_path.with_suffix(".md")
    json_path.parent.mkdir(parents=True, exist_ok=True)
    json_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    lines = [
        "# Workspace OS 控制平面",
        "",
        f"- 总体状态：**{report['status'].upper()}**",
        f"- 更新时间：{report['generated_at']}",
        "",
        "## 活跃告警",
        "",
    ]
    if report["alerts"]:
        lines.extend(
            f"- **{item['severity']}** `{item['source']}/{item['code']}` — {item['message']}（`{item['path']}`）"
            for item in report["alerts"]
        )
    else:
        lines.append("- 无活跃告警。")
    md_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return json_path, md_path
