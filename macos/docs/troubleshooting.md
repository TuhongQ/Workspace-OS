# 故障排查

- 中文路径异常：确认终端与文件均使用 UTF-8；PowerShell 7 优先。
- `python` 找不到：运行 `py -3.11` 或使用 Python 的绝对路径。
- 拒绝创建项目：目标已存在或名称含跨平台非法字符；工具不会覆盖。
- Inbox 没有移动：这是默认行为，先查看计划，确认后显式加 `--apply`。
- 发布目录非空：选择新版本目录，不要强制覆盖。
- 索引较慢：默认不计算哈希；仅在需要内容校验时加 `--hash`。
- macOS 权限错误：在系统设置给终端/NAS 客户端授予目标目录访问权，再以 dry-run 重试。

## 搜索索引异常

- 先运行 `search-check --database <workspace-search.db>`，查看 `quick_check`、必需表、计数与 FTS 遍历结果。
- `using_fallback=true`：当前库已损坏但 last-good 仍可查询；运行 `search-maintain --workspace <路径> --content` 完整重建。
- `INDEX_MAINTENANCE_FAILED`：候选库构建或校验失败，原有有效索引未被覆盖；检查磁盘空间与报告中的 `issues` 后重试。
- `INDEX_UNAVAILABLE`：当前库与 last-good 均不可用；保留损坏文件用于排查，从 Workspace 事实来源重建。不要把派生 SQLite 当成唯一副本。
