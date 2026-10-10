# 已验证快照独立介质导出

本流程把“复制到另一个盘符”升级为可验证证据。目标必须同时满足：

- 使用专用子目录并存在 Workspace OS 介质身份标记。
- 操作者显式确认它是另一块物理设备，而非同盘分区。
- 目标卷同时不同于 Workspace 和快照源所在卷。
- 源快照导出前通过完整清单、大小与 SHA-256 校验。
- 目标先写入同介质 staging，完整回读后再原子切换。
- 正式目标已存在时绝不覆盖；任何流程都不删除用户文件。

## 初始化外置介质

先创建专用目录，例如 `E:\WorkspaceOS-Backup`。预览不会写入：

```powershell
python scripts/python/workspace_cli.py backup-media-init `
  --destination "E:\WorkspaceOS-Backup" `
  --label "Offline SSD" `
  --confirm-distinct-physical-media
```

确认目标确实是独立设备后再添加 `--apply`。命令只创建
`.workspace-os-backup-media.json`，不会格式化、清空或加密介质，也拒绝覆盖已有标记。

PowerShell 入口：

```powershell
.\scripts\windows\Initialize-WorkspaceBackupMedia.ps1 `
  -Destination "E:\WorkspaceOS-Backup" `
  -Label "Offline SSD" `
  -ConfirmDistinctPhysicalMedia `
  -WhatIf
```

## 导出最新快照

先预览：

```powershell
.\scripts\windows\Export-WorkspaceSnapshot.ps1 `
  -MediaPath "E:\WorkspaceOS-Backup" `
  -WhatIf
```

确认后去掉 `-WhatIf`。提交成功会生成：

- `WorkspaceOS-Snapshots/<快照名>`：与源清单完全一致的只读恢复点。
- `WorkspaceOS-Receipts/<快照名>-<清单摘要>.json`：介质、卷、清单与回读结果绑定收据。
- `08_Indexes/Recovery/snapshot-export.json`：本机控制平面状态。

只有状态为 `exported` 或 `existing-verified`、源/目标均验证、收据存在、覆盖和删除为 0、
且对应当前最新快照时，恢复就绪度才把它计为第二种介质。

## 中断恢复

复制事务先写入 `.workspace-os-transactions`。如果进程或供电中断，下次显式执行会把残留
staging 和事务日志成对移动到
`_WorkspaceOS_Trash/InterruptedSnapshotExports`，保留现场后重新开始。已提交且匹配的目标
只会重新校验并复用同一内容绑定收据，不会覆盖。

`--simulation` 仅用于隔离演练：允许同卷复制，但
`eligible_for_distinct_media=false`，不会提高生产恢复分数。

## 安全边界

介质身份标记是人工物理确认，不是硬件证明；卷差异校验提供第二道门禁。导出没有加密能力，
敏感外置盘仍应使用 BitLocker/FileVault 或加密 restic 仓库。独立本地介质也不是异地副本，
不能单独满足完整 3-2-1。
