# 30 分钟快速开始

## 0–5 分钟：准备

安装 Python 3.11+，打开终端进入本项目，运行 `python scripts/python/workspace_cli.py --help`。先复制 `config/workspace.example.yaml`，只修改本机路径，不写密码或 Token。

## 5–10 分钟：创建 Workspace

```powershell
python scripts/python/workspace_cli.py init --path "D:\Workspace"
python scripts/python/workspace_cli.py new software FirstProject --space work --workspace "D:\Workspace"
python scripts/python/workspace_cli.py new video LifeVideo --space personal --workspace "D:\Workspace"
```

macOS 把路径换为 `~/Workspace`。创建器遇到同名项目会停止，不会覆盖。

## 10–15 分钟：设备路径

在本机同步工具中只选择当前项目、Knowledge、Prompts 与 Release；NAS 挂载到单一固定路径。iPhone 只上传到 `00_Inbox/Mobile`。不要让 iCloud、OneDrive 和 NAS 同时同步同一个物理目录。

## 15–20 分钟：审计和索引

```powershell
python scripts/python/workspace_cli.py audit --workspace "D:\Workspace"
python scripts/python/workspace_cli.py index --workspace "D:\Workspace"
```

报告位于 `08_Indexes/Audit/`，索引位于 `08_Indexes/workspace-index.json`。

## 20–25 分钟：NAS

创建 `Workspace`、`WorkspaceArchive`、`WorkspaceBackup`、`WorkspaceSnapshots`、`WorkspacePrivate` 五个共享目录，按 `nas/permissions.md` 分配最小权限；启用每日快照和每周外部备份。

## 25–30 分钟：处理 Inbox

把少量测试文件放入 `00_Inbox/ToSort`：

```powershell
python scripts/python/workspace_cli.py scan-inbox --workspace "D:\Workspace"
```

先阅读建议和日志。确认后才追加 `--apply`；移动前计划、移动后回滚记录都会保存在 `07_Admin/WorkspaceOS/logs`。
