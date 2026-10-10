# Workspace OS 2.0

一套面向 Windows、macOS、iPhone 与 NAS 的长期数字资产工作区。它把“唯一归属、渐进整理、可验证发布、可恢复迁移”固化为目录、模板和跨平台命令行，而不是依赖某个云服务。

## 当前能力

- 初始化完整 Workspace 目录，四类项目一键创建且拒绝覆盖。
- 工作项目与生活项目分区管理：`01_Projects/Work` 和 `01_Projects/Personal`。
- Inbox 默认只输出分类建议；只有显式 `--apply` 才移动，并生成计划、日志与回滚记录。
- 识别正式/工作/审核版本，排除缓存、临时文件和视频代理。
- 按大小与 SHA-256 检测二进制重复文件，不自动删除。
- 构建 JSON 索引，执行安全审计，生成发布清单和 `SHA256SUMS.txt`。
- 生成电脑/NAS 文件位置网页，标记仅电脑、仅 NAS、两边一致或版本冲突。
- Windows PowerShell 与 macOS Shell 入口调用同一套 Python 逻辑。
- Obsidian、NAS、iPhone 快捷指令、迁移和灾难恢复均有可执行流程。
- 生成无用户数据、双层 SHA-256 校验的便携恢复工具包，支持换机和跨设备安装。
- 生成防篡改设备清单、复制前冲突门禁和复制后完全一致收据，安全切换 Windows/Mac 主设备。
- 使用 metadata-only 可信基线检测批量删除、修改和疑似勒索扩展名，异常时冻结基线。
- 为派生控制平面报告建立连续哈希证据链，检测历史删除、篡改与当前状态漂移。
- 每周从最新已验证快照执行隔离 canary 恢复、回读 SHA-256 并测量观测 RTO。
- 跨设备事务执行器只提交 source-only 文件，执行前后复扫，拒绝覆盖并支持异常及断电恢复。
- SQLite FTS5 搜索采用候选库校验后原子切换，保留 last-good 索引；当前库损坏时查询可回退并从事实来源自愈重建。
- 已验证快照可事务式导出到独立物理介质：同卷阻断、staging 回读、原子提交、零覆盖收据和中断恢复。

## 5 分钟开始

需要 Python 3.11+：

```powershell
python scripts/python/workspace_cli.py --help
python scripts/python/workspace_cli.py init --path "D:\Workspace"
python scripts/python/workspace_cli.py new software DemoProject --workspace "D:\Workspace"
python scripts/python/workspace_cli.py index --workspace "D:\Workspace"
python scripts/python/workspace_cli.py audit --workspace "D:\Workspace"
python scripts/python/workspace_cli.py snapshot --workspace "D:\Workspace" --destination "D:\WorkspaceSnapshots" --apply
python scripts/python/workspace_cli.py backup-media-init --destination "E:\WorkspaceOS-Backup" --label "Offline SSD" --confirm-distinct-physical-media
python scripts/python/workspace_cli.py snapshot-export --snapshot "D:\WorkspaceSnapshots\Workspace_YYYYMMDD-HHMMSS" --media "E:\WorkspaceOS-Backup"
python scripts/python/workspace_cli.py doctor --workspace "D:\Workspace" --snapshots "D:\WorkspaceSnapshots" --nas "W:\"
python scripts/python/workspace_cli.py search-maintain --workspace "D:\Workspace" --content
python scripts/python/workspace_cli.py search-check --database "D:\Workspace\08_Indexes\Search\workspace-search.db"
python scripts/python/workspace_cli.py search "项目名" --database "D:\Workspace\08_Indexes\Search\workspace-search.db"
python scripts/python/workspace_cli.py graph-build --workspace "D:\Workspace"
python scripts/python/workspace_cli.py alerts --workspace "D:\Workspace"
python scripts/python/workspace_cli.py recovery-readiness --workspace "D:\Workspace" --snapshots "D:\WorkspaceSnapshots"
python scripts/python/workspace_cli.py recovery-kit-retention --destination "D:\Workspace\06_Release\Packages"
python scripts/python/workspace_cli.py device-manifest --workspace "D:\Workspace" --device-id "windows-main" --output "device.json"
python scripts/python/workspace_cli.py notifications --workspace "D:\Workspace"
python scripts/python/workspace_cli.py recovery-kit --destination "D:\Workspace\06_Release\Packages"
python scripts/python/workspace_cli.py change-guard --workspace "D:\Workspace"
python scripts/python/workspace_cli.py security-audit --workspace "D:\Workspace"
python scripts/python/workspace_cli.py evidence-verify --workspace "D:\Workspace" --verify-current
python scripts/python/workspace_cli.py restore-drill --workspace "D:\Workspace" --snapshot "D:\WorkspaceSnapshots\Workspace_YYYYMMDD-HHMMSS" --restore-root "D:\WorkspaceRestoreTests\Automated"
python scripts/python/workspace_cli.py device-apply --source-workspace "D:\Workspace" --target-workspace "E:\Workspace" --source-manifest source.json --target-manifest target.json
```

初始化只创建缺失内容，不覆盖已有文件。迁移、Inbox 移动和发布构建默认预览。详细步骤见 [快速开始](docs/quick-start.md)。

## 安全边界

本项目不提供永久删除命令；示例配置不含密码、Token、私钥；外部 AI 默认关闭内容上传；同步不被视为备份。任何正式变更前先保留快照或备份。

## 兼容性

- Python 3.11+
- PowerShell 5.1 / 7（已在 Windows 当前环境验证 Python 主流程）
- macOS 系统 Bash/Zsh（脚本语法已提供，未在当前 Windows 主机实机验证）
- 通用 NAS，并附 Synology/QNAP 建议

版本：见 `VERSION`；变更：见 `CHANGELOG.md`。

## 先试用首发版

解压 Windows 发行包后运行：

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File ".\scripts\windows\Start-WorkspaceOSTrial.ps1"
```

它只在 `%LOCALAPPDATA%\WorkspaceOS-Trial` 中创建隔离环境，并在快照、搜索、证据链、
安全扫描和 NEXUS 全部通过后写出 `trial-result.json`。详见
`docs/first-usable-release.md`。
