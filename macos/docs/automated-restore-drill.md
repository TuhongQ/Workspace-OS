# 自动隔离恢复演练

每周 canary 演练把“快照校验通过”进一步验证为“文件能够实际复制、回读并匹配原始
SHA-256”。它是快速恢复路径测试，不替代季度全量灾难恢复演练。

## 安全流程

1. 从 `backup-status.json` 取得最新快照，并确认独立全量校验证据的快照路径和清单
   SHA-256 都与当前对象完全一致。
2. 按快照清单哈希确定性排序，从可用的 Workspace 一级目录分层选择最多 16 个文件。
3. 排除 `Private`、`Accounts`、`Certificates`、`secrets` 和开发缓存；单文件默认不超过
   16 MB，总量不超过 128 MB。
4. 在 `D:\WorkspaceRestoreTests\Automated` 下创建随机命名临时目录。
5. 复制前校验快照源文件，复制后再次回读大小与 SHA-256。
6. 记录 canary 观测 RTO、文件数、字节数和目录计数，然后清理本次随机临时目录。

正式 Workspace 和快照均只读，不会被覆盖。报告不保存被抽样文件的路径，只保存相对路径
的 16 位不可逆 SHA-256 标识、目录计数和统计值。

如果全量验证报告缺少清单哈希、清单在验证后改变，或最近一次成功演练属于另一快照，系统
会拒绝沿用旧证据。恢复就绪度只有在验证报告和演练报告同时绑定当前快照时才计分。

## 手动执行

```powershell
.\scripts\windows\Test-WorkspaceRestoreDrill.ps1 `
  -WorkspacePath "D:\Workspace" `
  -SnapshotPath "D:\WorkspaceSnapshots" `
  -RestoreRoot "D:\WorkspaceRestoreTests\Automated"
```

也可直接使用 CLI：

```powershell
python scripts/python/workspace_cli.py restore-drill `
  --workspace "D:\Workspace" `
  --snapshot "D:\WorkspaceSnapshots\Workspace_YYYYMMDD-HHMMSS" `
  --restore-root "D:\WorkspaceRestoreTests\Automated"
```

结果写入 `08_Indexes/RecoveryDrills/latest-restore-drill.json`。失败时 CLI 返回退出码 2，
计划任务遥测会产生 ERROR；恢复就绪度同时产生缺失或失败告警。报告 Schema 位于
`search/restore-drill.schema.json`。

## 证据边界

canary RTO 只代表本次抽样数据的实际复制和校验时间，不能外推为整库恢复时间。季度演练仍应
恢复完整项目或完整 Workspace，并记录人员、设备、密钥和应用层可用性。
