# 维护清单

- 每日：确认备份任务、处理紧急 Inbox、检查磁盘告警。
- 每周：处理 ToSort、审计 Active 项目、抽查发布校验和。
- 每月：运行完整审计和重复报告，恢复一个随机文件，检查账户权限。
- 每季度：灾难恢复演练、更新设备清单、离线备份、审查长期未归档项目。
- 每年：检查格式可读性、存储容量、保留政策、软件版本和异地副本。

## Windows 自动维护

先预览将创建的任务：

```powershell
.\scripts\windows\Register-WorkspaceOSMaintenance.ps1 -WhatIf
```

确认恢复演练成功后注册九个当前用户任务：每日精简快照、每日 GFS 保留、每日健康报告、每日控制平面刷新、每周快照全量校验、每周隔离 canary 恢复、每周 Workspace 审计、每周便携恢复工具包，以及每周恢复包分层保留。

```powershell
.\scripts\windows\Register-WorkspaceOSMaintenance.ps1
```

脚本不会静默覆盖同名任务；只有显式添加 `-Replace` 才更新已有定义。磁盘密集型任务错峰执行，避免快照、校验与审计互相争用。
每周恢复包在周日 07:30 生成或复核，07:45 再执行分层保留；淘汰项只进入可恢复回收区。
每周日 04:30 先全量校验最新快照，05:00 再执行 canary 实际复制和回读哈希；临时恢复内容
完成后清理，报告进入恢复就绪度和证据链。
canary 演练体量受 16 文件 / 128 MB 上限约束，可在电池供电时运行；快照、全量校验和审计
等磁盘密集任务仍遵守 Windows 默认交流电保护。
健康报告写入 `08_Indexes/Health`。每次成功创建快照都会原子刷新
`08_Indexes/BackupVerification/latest-snapshot-verification.json`，每周全量校验任务再独立复核
最近快照并刷新同一份证据。每日控制平面还会刷新
`08_Indexes/Recovery/recovery-readiness.json`、计划任务遥测和去重通知发件箱；
只有新增 ERROR/CRITICAL 才触发桌面提醒。

每日控制平面还会根据 `config/maintenance-policy.json` 验证任务定义本身，而不只读取运行
结果。审计覆盖任务集合、脚本路径与 SHA-256、参数、Limited/Interactive 身份、单一触发器、
计划时间、执行时限和补跑策略，结果写入 `08_Indexes/Health/maintenance-audit.json`。
若合法升级改变任务参数，先使用 `Register-WorkspaceOSMaintenance.ps1 -Replace` 更新定义，
随后重新导出任务状态并确认完整性审计为 `healthy`。

任务定义故障注入应只使用复制出的 `scheduled-tasks.json`，不得修改生产计划任务。演练报告
保存在 `08_Indexes/AutomationDrills/latest-maintenance-integrity-drill.json`，并进入证据链。

每日控制平面还会运行变化哨兵。出现 WARNING 及以上时基线自动冻结；先保护现场并校验
快照，确认是合法批量操作后才运行 `change-guard --accept`。

每季度或安全态势出现 `PROTECTED_PATH_BROAD_WRITE` 时，先运行
`Protect-WorkspaceSensitiveDirectories.ps1` 的默认预览；确认当前用户、SYSTEM 和
Administrators 三类主体正确后才添加 `-Apply`。应用成功后保留
`07_Admin/WorkspaceOS/logs/acl-backups` 下的 ACL 恢复点，并重新运行安全态势审计。

每日控制平面开始时会校验 `08_Indexes/Evidence` 的历史连续性，结束时追加当前派生报告
哈希并执行 `--verify-current`。若出现 `EVIDENCE_CHAIN_INVALID`，不要重建或删除证据目录；
先复制现场、校验最近快照并检查 `status.json` 中的具体问题码。

每日检查 `08_Indexes/Search/search-status.json`：`healthy` 表示候选库已验证并切换；
`degraded` 需要关注 `INDEX_FALLBACK_ACTIVE` 或 `INDEX_MAINTENANCE_FAILED`，但查询仍可能可用；
`unavailable` 表示当前与 last-good 均不可用，应保留现场后运行 `search-maintain` 从事实来源重建。

每日检查 `08_Indexes/Operations/operational-slo.json`。前 7 个观测日为预热期，仅显示
`insufficient-data`；之后任一 SLO 的失败日超过预算会产生 WARNING，连续 3 个观测日失败
会产生 ERROR。每天只取最后一条记录计算，不因重复刷新增加权重。若
`operations-history-status.json` 无效，不要删除或重建历史；先保留现场并校验最近快照。

季度或修改运维历史逻辑后，在生产 Workspace 外执行隔离演练：

```powershell
python scripts/python/workspace_cli.py operations-drill `
  --workspace "D:\Workspace" `
  --drill-root "D:\WorkspaceRestoreTests\OperationsHistory_YYYYMMDD-HHMMSS"
```

演练只在隔离目录生成八天合成信号并故障注入，不读取业务文件内容；报告写入
`08_Indexes/OperationsDrills/latest-operations-history-drill.json` 并进入证据链。
