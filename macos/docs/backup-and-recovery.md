# 备份与恢复

同步不是备份，RAID 不是备份，快照也不能替代异地备份。采用 3-2-1：工作副本、NAS 快照/本地备份、外接盘或另一 NAS，并可增加加密云端副本。

建议：每小时快照保留 24 份；每日快照 30 份；每周完整/增量备份 12 份；每月离线或异地备份 12 份。每日检查任务状态，每周抽检 SHA-256，每月做单文件恢复，每季度做项目级灾难恢复。恢复顺序为停止同步、保护现场、选择恢复点、恢复到新目录、校验、业务确认、再切换。

## 创建本地快照

命令默认只预览；显式添加 `--apply` 才会复制。快照先写入临时目录，生成
`WORKSPACE-SNAPSHOT-MANIFEST.json`（目录、符号链接、文件大小与 SHA-256）并完成
全量校验后才原子切换为正式快照。目标已存在时拒绝覆盖。创建成功会原子刷新
`08_Indexes/BackupVerification/latest-snapshot-verification.json`，因此每日新快照会立即拥有
独立、可供恢复就绪度读取的全量校验证据，无需等待每周校验任务。
快照 schema 1.2 还会在复制前、复制后分别计算源 Workspace 的完整内容指纹，并与临时
快照指纹进行三方比较。复制期间只要出现文件新增、删除或内容变化，本次快照就会中止，
临时目录会被清理，`backup-status.json` 和正式目标均不会更新。这避免把不同时间点的文件
混合成一个看似有效的恢复点。

验证报告同时记录快照清单的 SHA-256。恢复就绪度只有在报告指向
`backup-status.json` 中的当前快照、清单哈希仍一致且验证未超过 8 天时，才把恢复点标记为
可信。清单被替换、报告过期或验证对象不一致都会撤销可信状态并产生告警。

```powershell
python scripts/python/workspace_cli.py snapshot --workspace "D:\Workspace" --destination "D:\WorkspaceSnapshots"
python scripts/python/workspace_cli.py snapshot --workspace "D:\Workspace" --destination "D:\WorkspaceSnapshots" --apply
```

完整基线快照应保留全部内容。日常快照可显式排除能由开发工具重新生成的缓存；预览结果会列出排除文件数与容量，清单也会永久记录所用策略：

```powershell
python scripts/python/workspace_cli.py snapshot --workspace "D:\Workspace" --destination "D:\WorkspaceSnapshots" --exclude-rebuildable-cache
python scripts/python/workspace_cli.py snapshot --workspace "D:\Workspace" --destination "D:\WorkspaceSnapshots" --exclude-rebuildable-cache --apply
```

PowerShell 也可运行：

```powershell
.\scripts\windows\New-WorkspaceSnapshot.ps1 -WorkspacePath "D:\Workspace" -Destination "D:\WorkspaceSnapshots" -WhatIf
.\scripts\windows\New-WorkspaceSnapshot.ps1 -WorkspacePath "D:\Workspace" -Destination "D:\WorkspaceSnapshots"
```

## 校验与隔离恢复

恢复永远写入全新目录。执行前后各做一次完整校验；快照校验失败、恢复后内容不一致或目标已经存在时都会阻止提交。

```powershell
python scripts/python/workspace_cli.py verify-snapshot "D:\WorkspaceSnapshots\Workspace_20260726-160000"
python scripts/python/workspace_cli.py restore "D:\WorkspaceSnapshots\Workspace_20260726-160000" --destination "D:\WorkspaceRestoreTest"
python scripts/python/workspace_cli.py restore "D:\WorkspaceSnapshots\Workspace_20260726-160000" --destination "D:\WorkspaceRestoreTest" --apply
```

每周自动 canary 演练会从最新已验证快照分层抽样，实际复制到随机隔离目录并回读 SHA-256：

```powershell
.\scripts\windows\Test-WorkspaceRestoreDrill.ps1
```

它记录观测 RTO 并清理本次临时内容，不覆盖 Workspace；详见
[自动隔离恢复演练](automated-restore-drill.md)。

canary 报告必须同时绑定当前快照路径与当前清单 SHA-256；旧快照的成功演练不能证明新快照
可恢复。每周全量验证也从 `backup-status.json` 的受控指针取得对象，不按清单内可修改的时间戳选取。

## GFS 保留策略

保留策略默认预览。执行后，淘汰快照会移动到 `_WorkspaceOS_Trash`，不会永久删除。
默认保留最近 24 个小时桶、30 个每日桶、12 个每周桶和 12 个月度桶，并始终保留最新快照。
基线或重要里程碑可固定，固定后永远不参与自动淘汰：

```powershell
python scripts/python/workspace_cli.py pin-snapshot "D:\WorkspaceSnapshots\Workspace_Baseline_20260726"
python scripts/python/workspace_cli.py retention --destination "D:\WorkspaceSnapshots"
python scripts/python/workspace_cli.py retention --destination "D:\WorkspaceSnapshots" --apply
```

先在实际设备完成一次恢复抽检，再单独启用计划任务。

## 恢复就绪度与 3-2-1 证明

以下命令不会修改备份，只汇总现有证据：

```powershell
python scripts/python/workspace_cli.py recovery-readiness `
  --workspace "D:\Workspace" `
  --snapshots "D:\WorkspaceSnapshots"
```

报告保存到 `08_Indexes/Recovery/recovery-readiness.json` 和同名 Markdown。分数由六项
独立证据组成：RPO 内的已验证快照、最近完整性校验、90 天内通过的隔离恢复演练、
不同介质、经过检查的加密异机副本、固定且无排除项的完整基线。

`confirmed_copies / confirmed_media / confirmed_offsite` 是保守计数。Workspace 与快照位于
同一卷时只算一种介质；NAS 文件位置缓存不算备份；只有存在显式仓库标记且最近检查通过的
加密异机仓库才计入异地副本。

不同盘符不自动等于不同物理介质。推荐使用
[已验证快照独立介质导出](backup-media-export.md)：介质标记、不同卷门禁、源/目标全量校验、
原子提交和内容绑定收据共同证明当前最新快照已进入另一介质。旧版
`backup-topology.json` 只作为兼容标记保留，不能覆盖同卷事实。

便携恢复工具包只负责在新设备上重新获得程序、文档和校验工具，不计入用户数据副本。
生成、验证和跨设备使用方式见 [便携恢复工具包](recovery-kit.md)。
