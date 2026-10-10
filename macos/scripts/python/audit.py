"""Workspace 审计器。只读扫描并输出 Markdown/JSON 报告。"""
from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from duplicate_finder import find_duplicates
from path_safety import iter_files_no_links, iter_paths_no_links
from version_detector import parse_version

FORBIDDEN = re.compile(
    r"(?:最终版?|最新版?|新的|新版|修改版|副本)|"
    r"(?<![A-Za-z0-9])(?:copy|new|final(?:[-_ ]?final)?)(?![A-Za-z0-9])",
    re.I,
)
TEMP_SUFFIXES = {".tmp", ".temp", ".part", ".crdownload"}
VERSION_REPLACER = re.compile(r"(?:20\d{2}[-_]?[01]\d[-_]?[0-3]\d|v\d+(?:\.\d+){0,2}|RELEASE|APPROVED|DRAFT|REVIEW|ARCHIVE|[_\-.])", re.I)
SKIP_DIRECTORY_NAMES = {".vs", "__pycache__", ".pytest_cache", "node_modules", ".venv"}
PROJECT_HINTS = {"src", "source", "release", "footage", "inputs", "documents", "requirements"}


def _looks_like_project(path: Path) -> bool:
    try:
        names = {child.name.lower() for child in path.iterdir() if child.is_dir()}
    except OSError:
        return False
    return bool(names & PROJECT_HINTS) or (path / "STATUS.md").exists() or (path / "README.md").exists()


def audit_workspace(root: str | Path, inbox_warning_count: int = 50, large_mb: int = 1024,
                    check_duplicates: bool = True, archive_after_days: int = 365) -> dict[str, Any]:
    base = Path(root).resolve()
    findings: list[dict[str, Any]] = []
    def add(severity: str, code: str, path: Path, message: str) -> None:
        findings.append({"severity": severity, "code": code, "path": str(path), "message": message})
    inbox = base / "00_Inbox" / "ToSort"
    if inbox.exists():
        count = sum(1 for p in iter_files_no_links(inbox) if p.is_file())
        if count >= inbox_warning_count:
            add("WARNING", "INBOX_BACKLOG", inbox, f"待分类文件 {count} 个")
    formal_groups: dict[str, list[Path]] = {}
    allowed_status = {"INBOX", "PLANNING", "ACTIVE", "BLOCKED", "REVIEW", "RELEASED", "PAUSED", "ARCHIVED"}
    safe_paths = list(iter_paths_no_links(base))
    for path in safe_paths:
        relative_parts_lower = {part.lower() for part in path.relative_to(base).parts}
        if relative_parts_lower & SKIP_DIRECTORY_NAMES:
            continue
        if path.is_dir():
            try:
                if not any(path.iterdir()):
                    add("INFO", "EMPTY_DIR", path, "目录为空；可放置 README.md 说明用途")
            except OSError:
                add("ERROR", "UNREADABLE", path, "目录不可读取")
            state_names = {"Active", "Paused", "Completed", "Sandbox"}
            direct_under_state = path.parent.name in state_names
            nested_under_state = path.parent.parent.name in state_names
            is_group = direct_under_state and any(_looks_like_project(child) for child in path.iterdir() if child.is_dir())
            is_project = (direct_under_state and not is_group) or (nested_under_state and _looks_like_project(path))
            if is_project:
                if not (path / "README.md").exists(): add("ERROR", "PROJECT_NO_README", path, "项目缺少 README.md")
                status_file = path / "STATUS.md"
                if not status_file.exists(): add("ERROR", "PROJECT_NO_STATUS", path, "项目缺少 STATUS.md")
                else:
                    status_text = status_file.read_text(encoding="utf-8", errors="replace")
                    current = re.search(r"当前状态[：:]\s*`?([A-Z]+)", status_text)
                    if not current or current.group(1) not in allowed_status:
                        add("ERROR", "PROJECT_INVALID_STATUS", status_file, "项目状态缺失或不在固定状态集合中")
                newest = max(
                    (
                        p.stat().st_mtime
                        for p in iter_files_no_links(path)
                        if p.is_file()
                    ),
                    default=path.stat().st_mtime,
                )
                if (datetime.now().timestamp() - newest) / 86400 > archive_after_days:
                    add("WARNING", "LONG_INACTIVE", path, f"项目超过 {archive_after_days} 天未更新且尚未归档")
            continue
        is_system_log = "WorkspaceOS" in path.parts and "logs" in path.parts
        if not is_system_log and FORBIDDEN.search(path.stem):
            add("WARNING", "FORBIDDEN_NAME", path, "文件名包含禁止使用的模糊版本词")
        parsed = parse_version(path)
        if parsed["status"] in {"RELEASE", "APPROVED"}:
            identity = VERSION_REPLACER.sub("", path.stem).lower()
            formal_groups.setdefault(identity, []).append(path)
        parts_lower = {part.lower() for part in path.parts}
        if ({"cache", "caches", "proxies"} & parts_lower) and ({"06_release", "release"} & parts_lower):
            add("ERROR", "CACHE_IN_FORMAL", path, "缓存或代理文件误存入正式发布范围")
        try:
            if path.stat().st_size > large_mb * 1024 * 1024 and path.suffix.lower() in TEMP_SUFFIXES:
                add("ERROR", "LARGE_TEMP", path, "发现超大临时文件")
        except OSError:
            add("ERROR", "UNREADABLE", path, "文件不可读取")
        if "release" in {part.lower() for part in path.parts} and path.is_dir():
            pass
    for release in [
        p for p in safe_paths
        if p.name.lower() == "release"
        and p.is_dir()
        and not ({part.lower() for part in p.parts} & SKIP_DIRECTORY_NAMES)
    ]:
        if not ((release.parent / "STATUS.md").exists() or "06_Release" in release.parts):
            continue
        payload = [
            p for p in iter_files_no_links(release)
            if p.is_file()
            and p.name not in {
                "README.md",
                "CHANGELOG.md",
                "release-manifest.json",
                "SHA256SUMS.txt",
            }
        ]
        if payload and not (release / "SHA256SUMS.txt").exists():
            add("ERROR", "RELEASE_NO_HASH", release, "发布目录缺少 SHA256SUMS.txt")
    for paths in formal_groups.values():
        if len(paths) > 1:
            add("WARNING", "MULTIPLE_FINAL", paths[0], f"发现 {len(paths)} 个疑似同一内容的正式/批准版本")
    backup_marker = base / "07_Admin" / "WorkspaceOS" / "backup-status.json"
    if not backup_marker.exists():
        add("INFO", "BACKUP_UNVERIFIED", backup_marker, "未发现备份状态标记；请按 NAS/备份系统实际结果更新")
    if check_duplicates:
        for group in find_duplicates(base):
            add("INFO", "DUPLICATE", Path(group["recommended_primary"]), f"发现 {group['file_count']} 个二进制重复文件")
    counts = {level: sum(1 for x in findings if x["severity"] == level) for level in ("INFO", "WARNING", "ERROR", "CRITICAL")}
    return {"generated_at": datetime.now(timezone.utc).isoformat(), "workspace": str(base),
            "summary": counts, "findings": findings}


def write_audit(report: dict[str, Any], output_dir: str | Path) -> tuple[Path, Path]:
    out = Path(output_dir); out.mkdir(parents=True, exist_ok=True)
    json_path, md_path = out / "audit-report.json", out / "audit-report.md"
    json_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    lines = ["# Workspace 审计报告", "", f"生成时间：{report['generated_at']}", f"工作区：`{report['workspace']}`", "",
             "## 摘要", "", *[f"- {k}: {v}" for k, v in report["summary"].items()], "", "## 发现", ""]
    lines += [f"- **{x['severity']}** `{x['code']}` `{x['path']}` — {x['message']}" for x in report["findings"]]
    md_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return md_path, json_path
