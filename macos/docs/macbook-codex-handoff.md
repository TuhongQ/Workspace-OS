# MacBook Codex 安装交接单

## 目标

在 MacBook 安装与 Windows 相同版本的 Workspace OS 2.0，并连接同一台群晖 NAS。Mac 本地工作区用于高速编辑，NAS 用于跨设备访问和集中保存；默认不启用自动同步、自动覆盖或自动删除。

## 已知环境

- 群晖地址：`192.168.1.9`
- DSM 管理界面：`http://192.168.1.9:5000`
- 主共享目录：`smb://192.168.1.9/Workspace`
- Mac 挂载目标：`/Volumes/Workspace`
- Mac 本地工作区：`~/Workspace`
- Workspace OS 程序目录：`~/CodeX/Workspace OS 2.0`
- NAS 安装包：`/Volumes/Workspace/06_Release/Packages` 中最新且带配套校验文件的 `WorkspaceOS-Recovery-Portable-2.0.0-*.zip`
- NAS 校验文件：与安装包同名的 `.sha256`
- NAS NEXUS 看板：`/Volumes/Workspace/08_Indexes/file-locations.html`

## 当前项目结构

```text
01_Projects（项目）
├── Work（工作）
│   ├── Active（进行中）
│   ├── Paused（已暂停）
│   └── Completed（已完成）
└── Personal（生活）
    ├── Active（进行中）
    ├── Paused（已暂停）
    └── Completed（已完成）
```

- 工作代码示例：`01_Projects/Work/Active/Xiaomi_项目名/src`
- 生活视频原片：`01_Projects/Personal/Active/视频项目名/footage`
- 生活视频成品：`01_Projects/Personal/Active/视频项目名/release`

## NAS 共享文件夹

- `Workspace`：主工作区和 NEXUS 看板。
- `WorkspaceArchive`：完成项目的长期归档。
- `WorkspaceBackup`：预留给加密异机备份；当前 Windows 工作区内已有 `07_Admin/WorkspaceOS/tools/restic.exe`，但系统命令未注册且未发现已初始化仓库，项目仍提供 `scripts/windows/Install-Restic.ps1` 安装脚本，MacBook 必须在目标机单独复核。
- `WorkspaceSnapshots`：预留给 NAS 快照或恢复点；Windows 本地校验快照已启用。
- `WorkspacePrivate`：敏感资料预留区；当前权限未收紧，不能视为真正私密。

## 直接粘贴给 MacBook Codex 的指令

```text
请帮我在这台 MacBook 上安装 Workspace OS 2.0，并持续执行到验证完成。

已知条件：
1. 群晖 NAS 地址是 192.168.1.9。
2. 主共享目录是 smb://192.168.1.9/Workspace，挂载后应为 /Volumes/Workspace。
3. 安装包是 /Volumes/Workspace/06_Release/Packages 中最新且带同名 .sha256 的 WorkspaceOS-Recovery-Portable-2.0.0-*.zip。

当 Windows Workspace 通过只读共享、外接盘或受控挂载在 Mac 上可见时，可使用
`scripts/macos/apply-device-handoff.sh` 执行 source-only 事务复制。必须先生成两端清单；
任何目标独有文件、冲突或清单过期都会阻断，工具不会覆盖或删除目标文件。
4. 如果有多个包，先逐个验证 SHA-256，只选择校验通过且源码指纹最新的包；不要仅凭文件名解压。
5. 程序安装到 ~/CodeX/Workspace OS 2.0，本地工作区使用 ~/Workspace。
6. 工作项目使用 01_Projects/Work/{Active,Paused,Completed}；生活项目使用 01_Projects/Personal/{Active,Paused,Completed}。

请按以下顺序操作：
- 先检查 NAS 是否已挂载；如未挂载，打开 Finder 的“连接服务器”界面让我输入群晖账号密码。不要向我索取或保存密码。
- 验证安装包 SHA-256 后再解压。校验失败立即停止，不要继续安装。
- 检查 python3 是否为 3.11 或更高；不足时说明原因并使用安全、可回退的方法安装，不要修改系统 Python。
- 将程序安装到 ~/CodeX/Workspace OS 2.0，并给 scripts/macos/*.sh 添加执行权限。
- 如果 ~/Workspace 不存在，先从 /Volumes/Workspace 复制建立本地初始副本；禁止使用带 --delete 的 rsync，禁止覆盖内容不同的现有文件。
- 如果 ~/Workspace 已存在，先只读比较本地与 NAS，报告差异后再决定复制，不能擅自覆盖。
- 使用 `generate-device-manifest.sh` 分别生成 Mac 与来源设备清单；复制前运行
  `compare-device-handoff.sh`，复制后运行 `verify-device-handoff.sh`。只有收据为
  `verified` 才切换主工作设备。
- 创建桌面入口：Workspace 本地、Workspace NAS、更新 NEXUS。
- 更新 NEXUS 时比较 ~/Workspace 与 /Volumes/Workspace，并把看板同时保存到两边的 08_Indexes。
- 运行全部自动化测试，并验证 NEXUS 中能看到容量、文件位置、中文目录别名、目录地图、使用说明和 NAS 说明。
- 不启用自动双向同步，不移动或删除用户文件，不修改 NAS 共享文件夹权限，不把同步当备份。
- 最后用中文告诉我：安装位置、桌面入口、测试结果、文件差异、尚未启用的功能，以及以后每天如何使用。

执行前先阅读安装包中的 README.md、docs/macbook-codex-handoff.md 和相关脚本。遇到现有文件或不确定的冲突时停止并询问，不要猜测。
```

## 验收标准

1. `python3 --version` 为 3.11 或更高。
2. `python3 -m unittest discover -s tests -v` 全部通过。
3. `~/Workspace/01_Projects/Work/Active` 和 `~/Workspace/01_Projects/Personal/Active` 存在。
4. `/Volumes/Workspace` 可读取。
5. `scripts/macos/update-nexus-dashboard.sh` 可生成并打开 NEXUS。
6. 本地和 NAS 的 `08_Indexes/file-locations.html` 同时存在。
7. 未配置自动同步、自动删除和自动覆盖。
8. 已生成 Mac 设备清单；如执行了迁移，交接收据为 `verified`。
