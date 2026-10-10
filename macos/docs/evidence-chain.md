# 控制平面证据链

证据链为每次自动维护保存一条不可覆盖的 JSON 记录，用于发现健康、告警、恢复、安全、
计划任务、设备清单和备份校验等派生报告的历史记录被修改或删除。

## 隐私边界

记录只包含 Workspace 内相对路径、是否存在、字节数和 SHA-256。它不保存报告内容、
业务文件内容、绝对路径、密码、Token 或私钥。默认只处理代码中明确列出的
`08_Indexes` 派生报告，包括运维历史状态、滚动 SLO 和隔离演练结果；不会扫描项目、
知识库或私人目录。

## 追加与校验

```powershell
python scripts/python/workspace_cli.py evidence-append `
  --workspace "D:\Workspace" `
  --event-type control-plane `
  --subject scheduled-maintenance

python scripts/python/workspace_cli.py evidence-verify `
  --workspace "D:\Workspace" `
  --verify-current
```

记录保存在 `08_Indexes/Evidence/records`。文件名由 20 位连续序号和记录哈希组成；
`head.json` 原子指向最后一条记录；`status.json` 保存最近校验结果。每条记录包含上一条
记录哈希、派生报告库存哈希和自身哈希。追加前必须先验证现有历史，验证失败时拒绝继续
追加，避免把损坏历史伪装成正常状态。

校验会发现：

- 记录内容或文件名被修改；
- 中间记录被删除、重复或序号断裂；
- `previous_hash` 链接断裂；
- `head.json` 与最后记录不一致；
- 使用 `--verify-current` 时，当前派生报告与最近证据不一致。

控制平面会在告警聚合前校验历史；无效时生成 CRITICAL
`EVIDENCE_CHAIN_INVALID`。维护结束后再追加当前证据并执行当前状态校验。

## 安全模型

这是防篡改检测，不是远程签名或 WORM 存储。拥有整个 Evidence 目录写权限的人可以重建
所有记录和 `head.json`。经过校验的快照、离线恢复包或未来的异机加密备份能保存独立副本，
从而提高重写历史的发现能力。不要在调查完成前删除或重建生产证据链。

记录 Schema 位于 `search/evidence-record.schema.json`。
