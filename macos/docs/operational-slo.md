# 运维历史与 SLO

Workspace OS 每次控制平面刷新后追加一条隐私最小化运行记录，用于回答两个问题：
“现在是否正常”和“最近一段时间是否持续可靠”。它不把业务文件清单复制进第二套数据库。

## 记录内容

每条记录只包含：

- `search_available`：当前搜索库或 last-good 是否可用；
- `snapshot_trusted`：恢复就绪度是否信任当前快照及其清单；
- `maintenance_integrity`：九个 Windows 维护任务的定义是否符合独立策略；
- `evidence_valid`：控制平面证据链是否有效；
- `scheduled_tasks_healthy`：维护任务是否启用且最近执行正常；
- 恢复分数，以及 WARNING、ERROR、CRITICAL 告警数量。

记录不包含业务文件内容、路径、文件名、凭据或知识库元数据。文件保存于
`08_Indexes/Operations/records`，采用 20 位连续序号、前向哈希、内容寻址文件名和原子
`head.json`。任何记录、顺序或 head 不一致都会使历史失效；系统会拒绝继续追加，以免
用新记录掩盖旧历史损坏。

## 30 天 SLO 与故障预算

`operational-slo.json` 默认使用最近 30 个自然日。一天内可能有多条刷新记录，但计算只取
当日序号最大的最后一条，因此频繁刷新不会改变该日权重。

| 信号 | 目标 |
| --- | ---: |
| 搜索可用 | 95% |
| 当前快照可信 | 100% |
| 维护任务定义完整 | 100% |
| 证据链有效 | 100% |
| 计划任务健康 | 95% |

前 7 个观测日只报告 `insufficient-data`。达到 7 日后，失败日超过允许数量会产生
`OPERATIONS_ERROR_BUDGET_EXHAUSTED`（WARNING）；连续 3 个观测日失败会产生
`OPERATIONS_CONSECUTIVE_FAILURES`（ERROR）。当前信号失败也会使 SLO 状态成为
`degraded`。

## 命令

```powershell
python scripts/python/workspace_cli.py operations-record `
  --workspace "D:\Workspace" `
  --window-days 30 `
  --dedupe-minutes 30

python scripts/python/workspace_cli.py operations-verify `
  --workspace "D:\Workspace"
```

`window-days` 必须至少为 1，`dedupe-minutes` 不能为负数。同一信号和计数组合在去重窗口内
不会重复追加，但仍会重新计算 SLO。

## 隔离故障演练

```powershell
python scripts/python/workspace_cli.py operations-drill `
  --workspace "D:\Workspace" `
  --drill-root "D:\WorkspaceRestoreTests\OperationsHistory_YYYYMMDD-HHMMSS"
```

演练根必须位于生产 Workspace 外，且必须不存在或为空。命令在隔离目录生成八个自然日的
合成报告，构造最后三日搜索失败，验证故障预算耗尽和连续失败告警；随后篡改第一条记录，
确认哈希校验失败且第九条记录被拒绝。演练不会读取业务文件内容，不覆盖或删除用户数据。

默认结果保存于
`08_Indexes/OperationsDrills/latest-operations-history-drill.json`，Schema 位于
`search/operations-history-drill.schema.json`。运维历史提供的是防篡改检测而非数字签名；
独立快照、离线介质和异机副本仍是防止攻击者重写全部本地历史的必要边界。
