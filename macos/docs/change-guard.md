# Workspace 变化哨兵

变化哨兵用于尽早发现批量删除、批量修改、疑似加密扩展名和勒索说明文件。它只读取
相对路径、大小、修改时间与扩展名，不读取文件内容、不上传数据、不自动删除或阻断进程。

## 日常运行

```powershell
python scripts/python/workspace_cli.py change-guard --workspace "D:\Workspace"
```

首次运行建立学习基线并返回 `learning`。正常的下一次运行返回 `healthy` 并原子更新基线。
每日控制平面会自动执行此命令。

主要产物：

- `08_Indexes/Security/change-baseline.json`：可信 metadata-only 基线。
- `08_Indexes/Security/change-guard.json`：本次差异、阈值、发现和最多 20 条本地样本。

## 异常判定

- 删除达到上次文件数的 10%，且不少于 25 个：ERROR。
- 修改达到上次文件数的 35%，且不少于 100 个：ERROR。
- 至少 3 个原文件被替换为 `.locked`、`.encrypted`、`.crypt` 等扩展名：CRITICAL。
- 单个疑似加密扩展名：WARNING。
- 出现 `HOW_TO_DECRYPT`、`RESTORE_FILES` 等疑似勒索说明文件：CRITICAL。

阈值是早期信号，不是恶意软件定论。ERROR/CRITICAL 会进入统一告警、通知发件箱和
Windows 桌面提醒。

## 基线冻结

存在任何 WARNING/ERROR/CRITICAL 时，可信基线不会更新。先断开同步和可疑网络连接，
保护现场与告警报告，校验最近快照，再判断变化是正常批量操作还是安全事件。

只有确认变化合法后，才显式接受：

```powershell
python scripts/python/workspace_cli.py change-guard `
  --workspace "D:\Workspace" `
  --accept
```

`--accept` 会更新基线，但不会移动、恢复或删除任何用户文件。

## 隐私与排除

开发缓存、`.git`、`07_Admin/WorkspaceOS` 和整个 `08_Indexes` 不进入变化基线，避免系统
自身刷新产生自激告警。全文搜索也排除整个 `08_Indexes`，因此基线中的路径不会被当作
普通文档内容索引。变化哨兵不代替 Defender/EDR、离线备份或恢复演练。
