"""Workspace、快照目标与 NAS 的统一健康检查。"""
from __future__ import annotations

import json
import os
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from path_safety import is_link_or_reparse, iter_files_no_links
from workspace_core import WORKSPACE_LAYOUT

CACHE_DIRECTORY_NAMES = {".vs", "__pycache__", ".pytest_cache", "node_modules", ".venv"}


def _storage(path: Path) -> dict[str, Any]:
    probe = path
    while not probe.exists() and probe != probe.parent:
        probe = probe.parent
    usage = shutil.disk_usage(probe)
    free_percent = round(usage.free / usage.total * 100, 2) if usage.total else 0
    return {
        "path": str(path),
        "probe": str(probe),
        "total_bytes": usage.total,
        "free_bytes": usage.free,
        "free_percent": free_percent,
    }


def workspace_health(
    workspace: str | Path,
    snapshots: str | Path | None = None,
    nas: str | Path | None = None,
    backup_max_age_hours: int = 26,
    nas_probe: dict[str, Any] | None = None,
) -> dict[str, Any]:
    root = Path(workspace).expanduser().resolve()
    findings: list[dict[str, Any]] = []

    def add(severity: str, code: str, path: str | Path, message: str, **details: Any) -> None:
        findings.append({
            "severity": severity,
            "code": code,
            "path": str(path),
            "message": message,
            **details,
        })

    if not root.is_dir() or not (root / ".workspace-os.json").is_file():
        add("CRITICAL", "WORKSPACE_UNAVAILABLE", root, "Workspace 不可用或缺少标记文件")
    else:
        missing = [name for name in WORKSPACE_LAYOUT if not (root / name).is_dir()]
        if missing:
            add("ERROR", "LAYOUT_INCOMPLETE", root, "Workspace 一级目录不完整", missing=missing)
        inbox = root / "00_Inbox" / "ToSort"
        inbox_count = (
            sum(1 for path in iter_files_no_links(inbox) if path.is_file())
            if inbox.exists()
            else 0
        )
        if inbox_count >= 50:
            add("WARNING", "INBOX_BACKLOG", inbox, f"待分类文件达到 {inbox_count} 个", count=inbox_count)

        cache_bytes = 0
        cache_files = 0
        cache_roots: list[str] = []
        for current, dirnames, filenames in os.walk(root):
            current_path = Path(current)
            dirnames[:] = [
                name for name in dirnames
                if not is_link_or_reparse(current_path / name)
            ]
            if current_path.name in CACHE_DIRECTORY_NAMES:
                cache_roots.append(str(current_path))
                for child_root, child_dirs, child_files in os.walk(current_path):
                    child_path = Path(child_root)
                    child_dirs[:] = [
                        name for name in child_dirs
                        if not is_link_or_reparse(child_path / name)
                    ]
                    for name in child_files:
                        try:
                            cache_bytes += (Path(child_root) / name).stat().st_size
                            cache_files += 1
                        except OSError:
                            pass
                dirnames[:] = []
                continue
            for name in filenames:
                if Path(name).suffix.lower() == ".ipch":
                    try:
                        cache_bytes += (current_path / name).stat().st_size
                        cache_files += 1
                    except OSError:
                        pass
        if cache_bytes:
            add(
                "INFO",
                "REBUILDABLE_CACHE",
                root,
                f"发现 {cache_files} 个可重建缓存文件，占用 {cache_bytes / 1024**3:.2f} GiB",
                bytes=cache_bytes,
                files=cache_files,
                cache_roots=cache_roots[:20],
            )

        status_path = root / "07_Admin" / "WorkspaceOS" / "backup-status.json"
        if not status_path.is_file():
            add("WARNING", "BACKUP_STATUS_MISSING", status_path, "尚无已验证快照状态")
        else:
            try:
                status = json.loads(status_path.read_text(encoding="utf-8"))
                verified_at = datetime.fromisoformat(status["verified_at"].replace("Z", "+00:00"))
                if verified_at.tzinfo is None:
                    verified_at = verified_at.replace(tzinfo=timezone.utc)
                age_hours = (datetime.now(timezone.utc) - verified_at).total_seconds() / 3600
                if not status.get("verified"):
                    add("CRITICAL", "BACKUP_NOT_VERIFIED", status_path, "最近快照未通过完整性校验")
                elif age_hours > backup_max_age_hours:
                    add("WARNING", "BACKUP_STALE", status_path, f"最近验证距今 {age_hours:.1f} 小时", age_hours=round(age_hours, 2))
                if not Path(status.get("last_snapshot", "")).is_dir():
                    add("ERROR", "BACKUP_TARGET_MISSING", status_path, "状态文件记录的最近快照当前不可访问")
            except (OSError, ValueError, KeyError, TypeError, json.JSONDecodeError):
                add("ERROR", "BACKUP_STATUS_INVALID", status_path, "备份状态文件不可读或结构无效")

    for label, target in (("WORKSPACE", root), ("SNAPSHOTS", Path(snapshots).expanduser().resolve() if snapshots else None)):
        if target is None:
            continue
        try:
            storage = _storage(target)
            severity = "CRITICAL" if storage["free_percent"] < 10 else "WARNING" if storage["free_percent"] < 20 else "INFO"
            add(
                severity,
                f"{label}_STORAGE",
                target,
                f"可用空间 {storage['free_percent']}%",
                storage={key: value for key, value in storage.items() if key != "path"},
            )
        except OSError:
            add("ERROR", f"{label}_STORAGE_UNAVAILABLE", target, "无法读取存储容量")

    if snapshots:
        snapshot_root = Path(snapshots).expanduser().resolve()
        if snapshot_root.exists():
            partials = [path for path in snapshot_root.iterdir() if path.is_dir() and ".partial-" in path.name]
            if partials:
                add("WARNING", "INCOMPLETE_SNAPSHOT", snapshot_root, f"发现 {len(partials)} 个未完成快照", paths=[str(path) for path in partials])

    if nas:
        nas_root = Path(nas).expanduser()
        if nas_probe is not None:
            probe_status = str(nas_probe.get("status") or "unknown")
            probe_details = {
                "probe_status": probe_status,
                "probe_generated_at": nas_probe.get("generated_at"),
                "duration_ms": nas_probe.get("duration_ms"),
            }
            if probe_status == "available" and nas_probe.get("marker_valid"):
                add("INFO", "NAS_AVAILABLE", nas_root, "NAS 可访问且标记有效", **probe_details)
            elif probe_status == "available":
                add("WARNING", "NAS_MARKER_MISSING", nas_root, "NAS 可访问但缺少 Workspace 标记", **probe_details)
            elif probe_status == "timeout":
                add("WARNING", "NAS_PROBE_TIMEOUT", nas_root, "NAS 健康探测超过安全时限", **probe_details)
            else:
                add("WARNING", "NAS_UNAVAILABLE", nas_root, "NAS 当前不可访问", **probe_details)
        elif not nas_root.exists():
            add("WARNING", "NAS_UNAVAILABLE", nas_root, "NAS 当前不可访问")
        elif not (nas_root / ".workspace-os.json").is_file():
            add("WARNING", "NAS_MARKER_MISSING", nas_root, "NAS 可访问但缺少 Workspace 标记")
        else:
            add("INFO", "NAS_AVAILABLE", nas_root, "NAS 可访问且标记有效")

    rank = {"INFO": 0, "WARNING": 1, "ERROR": 2, "CRITICAL": 3}
    highest = max((rank[item["severity"]] for item in findings), default=0)
    status = "critical" if highest >= 3 else "error" if highest == 2 else "warning" if highest == 1 else "healthy"
    counts = {level: sum(1 for item in findings if item["severity"] == level) for level in rank}
    return {
        "schema_version": "1.0",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "workspace": str(root),
        "status": status,
        "summary": counts,
        "findings": findings,
    }


def save_health(report: dict[str, Any], output: str | Path) -> tuple[Path, Path]:
    target = Path(output)
    json_path = target if target.suffix.lower() == ".json" else target.with_suffix(".json")
    md_path = json_path.with_suffix(".md")
    json_path.parent.mkdir(parents=True, exist_ok=True)
    json_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    lines = [
        "# Workspace OS 健康报告",
        "",
        f"- 状态：**{report['status'].upper()}**",
        f"- 生成时间：{report['generated_at']}",
        f"- Workspace：`{report['workspace']}`",
        "",
        "## 检查结果",
        "",
    ]
    lines.extend(
        f"- **{item['severity']}** `{item['code']}` — {item['message']}（`{item['path']}`）"
        for item in report["findings"]
    )
    md_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return json_path, md_path
