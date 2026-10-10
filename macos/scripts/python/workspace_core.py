"""Workspace 初始化、项目创建和 Inbox 计划执行。"""
from __future__ import annotations

import json
import shutil
from datetime import datetime, timezone
from pathlib import Path, PureWindowsPath
from typing import Any

from classifier import classify_file
from path_safety import find_link_entries, iter_files_no_links

WORKSPACE_LAYOUT = {
    "00_Inbox": ["Downloads", "WeChat", "Email", "AirDrop", "Mobile", "ToSort", "Quarantine"],
    "01_Projects": ["Work", "Work/Active", "Work/Paused", "Work/Completed",
                    "Personal", "Personal/Active", "Personal/Paused", "Personal/Completed"],
    "02_Knowledge": ["Programming", "AI", "Automation", "Video", "NAS", "Devices", "Workflows", "Notes"],
    "03_Assets": ["Video", "Images", "Audio", "Fonts", "Icons", "Templates", "Stock", "Brand"],
    "04_AI": ["Prompts", "Workflows", "Agents", "Models", "Datasets", "Generated", "Conversations", "Evaluations"],
    "05_Media": ["YouTube", "Bilibili", "Douyin", "Xiaohongshu", "Courses", "ProductDemo", "Internal"],
    "06_Release": ["Apps", "Installers", "Documents", "Videos", "Packages", "Checksums"],
    "07_Admin": ["Contracts", "Finance", "Licenses", "Devices", "Accounts", "Certificates", "Private"],
    "08_Indexes": ["ProjectIndex", "AssetIndex", "ReleaseIndex", "DeviceIndex", "ArchiveIndex"],
    "09_Templates": ["Project", "Document", "Media", "AI", "README"],
    "99_Archive": ["Projects", "Assets", "Releases", "Legacy", "ByYear"],
}
PROJECT_TEMPLATE = {"software": "SoftwareProject", "ai": "AIProject", "video": "VideoProject", "work": "WorkProject"}
STATUS_VALUES = "INBOX / PLANNING / ACTIVE / BLOCKED / REVIEW / RELEASED / PAUSED / ARCHIVED"
PROJECT_DIRECTORY_HELP = {
    "Work": "工作项目空间。客户、公司、代码和正式工作资料统一放在这里。",
    "Work/Active": "正在进行的工作项目，例如 `Xiaomi_项目名`。源码放项目内的 `src`。",
    "Work/Paused": "暂时停止、以后可能继续的工作项目。",
    "Work/Completed": "已经完成并验收的工作项目。",
    "Personal": "生活项目空间。家庭、旅行、兴趣和个人创作统一放在这里。",
    "Personal/Active": "正在进行的生活项目，例如生活视频。原片放项目内的 `footage`。",
    "Personal/Paused": "暂时停止、以后可能继续的生活项目。",
    "Personal/Completed": "已经完成的生活项目，视频成品保留在项目内的 `release`。",
}


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _safe_target(path: str | Path) -> Path:
    raw = str(path)
    if PureWindowsPath(raw).anchor.startswith("\\\\"):
        return Path(raw)
    target = Path(path).expanduser().resolve()
    # 本地磁盘根目录（如 C:\）范围过大，必须拒绝；UNC 的 share 根目录
    # （如 \\nas\Workspace）本身就是明确的目标边界，应当允许。
    is_unc_share = str(target).startswith("\\\\") and target.anchor.startswith("\\\\")
    if target == Path(target.anchor) and not is_unc_share:
        raise ValueError("拒绝对磁盘根目录执行操作")
    return target


def _write_new(path: Path, content: str, dry_run: bool = False) -> bool:
    if path.exists():
        return False
    if not dry_run:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
    return True


def init_workspace(path: str | Path, dry_run: bool = False) -> dict[str, Any]:
    root = _safe_target(path)
    operations = []
    for top, children in WORKSPACE_LAYOUT.items():
        for folder in [root / top, *[root / top / child for child in children]]:
            operations.append({"action": "ensure-directory", "path": str(folder)})
            if not dry_run: folder.mkdir(parents=True, exist_ok=True)
        readme = root / top / "README.md"
        content = (f"# {top}\n\n- **这里存什么**：符合 `{top}` 分类且已有明确归属的内容。\n"
                   "- **不存什么**：缓存、临时副本和无法判断归属的文件。\n"
                   "- **何时移入**：完成 Inbox 人工确认后。\n- **何时归档**：项目结束或长期不再活跃时。\n"
                   "- **推荐命名**：`主题_YYYY-MM-DD_v版本_状态.扩展名`。\n")
        if _write_new(readme, content, dry_run): operations.append({"action": "create-file", "path": str(readme)})
        for child in children:
            child_readme = root / top / child / "README.md"
            description = PROJECT_DIRECTORY_HELP.get(child, "只存放与该分类直接相关、已确认归属的文件。")
            child_content = (f"# {child}\n\n{description}\n\n本目录属于 `{top}/{child}`；未确认内容先留在 "
                             "`00_Inbox/ToSort`。项目结束或超过保留策略后移入 `99_Archive`，不直接删除。\n")
            if _write_new(child_readme, child_content, dry_run):
                operations.append({"action": "create-file", "path": str(child_readme)})
    logs = root / "07_Admin" / "WorkspaceOS" / "logs"
    if not dry_run: logs.mkdir(parents=True, exist_ok=True)
    _write_new(logs / "README.md", "# Workspace OS 日志\n\n保存操作计划、执行日志和回滚记录；不得写入密码、Token 或私密内容。\n", dry_run)
    marker = root / ".workspace-os.json"
    if _write_new(marker, json.dumps({"version": "2.0.0", "created_at": datetime.now(timezone.utc).isoformat()}, ensure_ascii=False, indent=2), dry_run):
        operations.append({"action": "create-file", "path": str(marker)})
    return {"workspace": str(root), "dry_run": dry_run, "operations": operations}


def new_project(kind: str, name: str, workspace: str | Path, dry_run: bool = False,
                destination: str | None = None, space: str = "work") -> dict[str, Any]:
    if kind not in PROJECT_TEMPLATE: raise ValueError(f"未知项目类型: {kind}")
    if space not in {"work", "personal"}: raise ValueError("项目空间必须是 work 或 personal")
    if not name.strip() or any(c in name for c in '<>:"/\\|?*'):
        raise ValueError("项目名为空或包含跨平台非法字符")
    root = _safe_target(workspace)
    if destination is None:
        destination = f"01_Projects/{'Work' if space == 'work' else 'Personal'}/Active"
    target = root / destination / name
    template = _repo_root() / "templates" / PROJECT_TEMPLATE[kind]
    if target.exists(): raise FileExistsError(f"目标项目已存在，拒绝覆盖: {target}")
    plan = {"kind": kind, "name": name, "space": space, "source_template": str(template), "target": str(target), "dry_run": dry_run}
    if dry_run: return plan
    unsafe_template = find_link_entries(template)
    if unsafe_template:
        relative = unsafe_template[0].relative_to(template).as_posix()
        raise ValueError(f"UNSAFE_PROJECT_TEMPLATE_LINK: {relative}")
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(template, target, symlinks=True)
    unsafe_target = find_link_entries(target)
    if unsafe_target:
        relative = unsafe_target[0].relative_to(target).as_posix()
        shutil.rmtree(target)
        raise ValueError(f"UNSAFE_PROJECT_OUTPUT_LINK: {relative}")
    for file in iter_files_no_links(target):
        if file.is_file():
            text = file.read_text(encoding="utf-8").replace("{{PROJECT_NAME}}", name).replace("{{DATE}}", datetime.now().date().isoformat())
            file.write_text(text, encoding="utf-8")
    _log(root, "new-project", plan)
    return plan


def _log(workspace: Path, action: str, data: dict[str, Any]) -> Path:
    folder = workspace / "07_Admin" / "WorkspaceOS" / "logs"
    folder.mkdir(parents=True, exist_ok=True)
    target = folder / f"{datetime.now().strftime('%Y%m%d-%H%M%S-%f')}_{action}.json"
    target.write_text(json.dumps({"timestamp": datetime.now(timezone.utc).isoformat(), **data}, ensure_ascii=False, indent=2), encoding="utf-8")
    return target


def scan_inbox(workspace: str | Path, apply: bool = False) -> dict[str, Any]:
    root = _safe_target(workspace)
    inbox = root / "00_Inbox" / "ToSort"
    plans = [
        classify_file(path)
        for path in sorted(iter_files_no_links(inbox))
        if path.is_file()
    ]
    report = {"workspace": str(root), "mode": "apply" if apply else "dry-run", "plans": plans, "executed": []}
    plan_path = _log(root, "inbox-plan", report)
    report["plan_log"] = str(plan_path)
    if not apply: return report
    rollback = []
    for item in plans:
        source = Path(item["source"])
        destination = root / item["suggested_target"] / item["suggested_name"]
        if destination.exists():
            item["skipped"] = "目标已存在，拒绝覆盖"; continue
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(source), str(destination))
        rollback.append({"from": str(destination), "to": str(source)})
        report["executed"].append({"from": str(source), "to": str(destination)})
    rollback_path = _log(root, "inbox-rollback", {"operations": rollback})
    report["rollback_log"] = str(rollback_path)
    return report
