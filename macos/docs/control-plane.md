# Workspace OS 控制平面

控制平面每天顺序刷新：

1. SQLite FTS5 候选库增量更新、完整性校验、原子切换与 last-good 回退。
2. 项目、客户分组、Obsidian 双链与项目文档关系图。
3. Workspace、快照容量和 NAS 健康检查。
4. metadata-only 变化哨兵与可信基线冻结。
5. 恢复就绪度、3-2-1 覆盖与自动维护任务遥测。
6. 审计、备份、搜索、关系图、安全变化和恢复能力的统一告警。
7. 隐私最小化、带去重指纹的通知发件箱。
8. NEXUS 看板，并尝试将只读 HTML/JSON 副本发布到 NAS。
9. 本机跨设备内容清单，以及最近一次交接门禁或收据状态。
10. 控制平面派生报告的连续哈希证据链；开始时校验历史，结束时追加并核对当前状态。
11. 最近自动 canary 恢复演练的文件数、观测 RTO 和临时内容清理状态。
12. 最近跨设备事务复制的状态、文件数，以及覆盖/删除恒为零的不变量。
13. 隐私最小化运维历史、30 天滚动 SLO、故障预算与连续失败状态。

主要产物：

- `08_Indexes/Search/workspace-search.db`
- `08_Indexes/Search/search-status.json`
- `08_Indexes/Graph/workspace-graph.json`
- `08_Indexes/Health/workspace-health.json`
- `08_Indexes/Health/scheduled-tasks.json`
- `08_Indexes/Health/maintenance-audit.json`
- `08_Indexes/Recovery/recovery-readiness.json`
- `08_Indexes/Security/change-baseline.json`
- `08_Indexes/Security/change-guard.json`
- `08_Indexes/Security/security-audit.json`
- `08_Indexes/Security/security-posture.json`
- `08_Indexes/Security/encryption-evidence.json`
- `08_Indexes/Security/acl-hardening.json`
- `08_Indexes/Alerts/control-plane.json`
- `08_Indexes/Alerts/nas-publish-status.json`
- `08_Indexes/Alerts/notification-outbox.json`
- `08_Indexes/Alerts/notification-state.json`
- `08_Indexes/file-locations.html`
- `08_Indexes/Evidence/records/*.json`
- `08_Indexes/Evidence/head.json`
- `08_Indexes/Evidence/status.json`
- `08_Indexes/RecoveryDrills/latest-restore-drill.json`
- `08_Indexes/Devices/device-apply-status.json`
- `08_Indexes/Operations/records/*.json`
- `08_Indexes/Operations/head.json`
- `08_Indexes/Operations/operations-history-status.json`
- `08_Indexes/Operations/operational-slo.json`
- `08_Indexes/OperationsDrills/latest-operations-history-drill.json`

日常 NEXUS 刷新复用上次 NAS 元数据，避免 SMB 目录枚举阻塞。需要发现 NAS 新增或删除文件时，
显式运行 `locations --refresh-nas` 或
`Update-LocationDashboard.ps1 -RefreshNas`。缓存模式会在 NEXUS“系统状态”页面明确显示，
不会伪装成实时扫描。缓存缺失或根路径不匹配时显示 `cache-miss`，且不会自动退回实时扫描。
同一 NAS 在盘符和 UNC 路径之间切换时，可信缓存会以 `cached-alias` 模式复用；也可用
`locations --nas-cache <本地快照 JSON>` 从已验证快照恢复缓存。

连最轻量的 NAS 存在性和标记检查也在独立进程中执行，5 秒未完成即终止并写入本地
`08_Indexes/Health/nas-probe.json`。`doctor` 在计划任务中只读取这份本地证据，
不会直接触碰可能失去响应的 SMB 路径。

NAS 仪表盘发布在独立 PowerShell 进程中执行，先写入进程级临时文件再原子切换，避免直接
覆盖 SMB 文件时长时间阻塞或暴露半成品；默认设有 60 秒硬超时。远端不可用时，
本地维护仍会正常结束；失败详情写入 `nas-publish-status.json`，并作为 WARNING
汇总到告警中心。失败后默认进入 6 小时熔断窗口，期间本地刷新继续执行但不重复等待 SMB。

NAS 上的 `file-locations.html` 是可直接打开的自包含看板。为适应低吞吐 SMB，
机器数据以 `file-locations.json.gz` 发布；`file-locations.json` 是小型描述清单，
记录压缩格式、文件名、原始大小与 SHA-256。未压缩完整 JSON 只保留在本地控制平面。
发布进程启动时会把超过 6 小时的 `.file-locations.*.partial` 移入 NAS 的
`08_Indexes/_WorkspaceOS_Trash/NexusPublish`，并将回收证据写入本地
`08_Indexes/Alerts/nas-publish-recovery.json`；不会永久删除中断产物。

Windows 维护任务的启用状态、上次结果与下次执行时间写入 `scheduled-tasks.json`。
任务禁用产生 WARNING，上次运行失败产生 ERROR，并进入统一告警中心。

任务遥测同时记录动作数量、PowerShell 执行器、脚本路径与 SHA-256、参数 token、运行身份、
触发器和关键设置。`maintenance-audit.json` 使用 `config/maintenance-policy.json` 独立核对
九个任务；缺失、额外任务、脚本/参数/时间漂移和 Highest 权限均告警，`-Command` 或
`-EncodedCommand` 等任意命令入口升级为 CRITICAL。该报告进入证据链，避免只凭“任务最近
返回 0”误判自动化仍可信。

每日控制平面结束前追加一条运维记录。记录只包含五个布尔健康信号、恢复分数和分级告警
计数；同一自然日的最后一次记录代表该日 SLO 状态，多次刷新不会人为放大样本。记录采用
连续序号、前向哈希和原子 `head.json`；历史失效时触发 CRITICAL 并拒绝追加。详细定义及
隔离演练见 [运维历史与 SLO](operational-slo.md)。

恢复就绪度将最近快照、SHA-256 校验、隔离恢复演练、固定完整基线、介质独立性和
加密异机副本合并为 0–100 分证据报告。它不会把“文件能在 NAS 上看到”误算成备份。

新增 ERROR/CRITICAL 会进入去重通知发件箱并触发 Windows 桌面提醒。通知载荷会移除
文件路径和凭据；如需 webhook，只从用户或进程环境变量
`WORKSPACEOS_ALERT_WEBHOOK_URL` 读取 URL，不写入仓库或报告。

变化哨兵只使用相对路径、大小、修改时间和扩展名。出现异常时冻结基线并保留证据；
只有人工复核后的显式 `change-guard --accept` 才接受当前状态。整个 `08_Indexes`
不进入全文搜索，避免安全基线中的路径被二次索引。

证据链只保存派生报告的相对路径、大小和 SHA-256，不保存报告或业务文件内容。记录必须
连续、前后哈希相连且与原子 `head.json` 一致；失效时触发 CRITICAL 并拒绝追加。
它是防篡改检测而非数字签名，完整安全边界见 [控制平面证据链](evidence-chain.md)。

ACL 加固报告记录固定受保护目录的预览、备份、应用与自检结果。它不会保存本机用户名，
也不会改变文件内容；只有显式执行 Windows 加固脚本才会修改 ACL。NEXUS 显示已验证目录数、
待变更数、内容覆盖/删除不变量和是否生成恢复点。

每周恢复演练从最新已验证快照执行实际隔离复制和 SHA-256 回读，详情见
[自动隔离恢复演练](automated-restore-drill.md)。canary 观测 RTO 不能替代季度全量演练。

搜索索引是可重建派生缓存。控制平面只在候选库通过 `quick_check`、表结构、计数和 FTS
遍历检查后切换；当前库损坏时查询使用 last-good，维护任务从 Workspace 事实来源完整重建。
详见 [搜索索引可靠性](search-reliability.md)。

恢复就绪度还会核对 `08_Indexes/Recovery/snapshot-export.json`。只有收据对应当前最新快照、
清单摘要匹配、目标回读通过、介质与 Workspace/快照源不同卷且覆盖/删除均为 0，才增加
独立介质与副本计数。介质离线时保留最近一次成功收据证据，但不会把它误算为异地加密副本。
