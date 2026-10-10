# 本地搜索索引可靠性

Workspace OS 将 SQLite FTS5 视为可重建但必须持续可用的本地派生资产。每日控制平面不再直接
修改正式数据库，而是维护候选库并在验证通过后原子切换。

## 维护流程

1. 只读检查当前库：SQLite `quick_check`、必需表、Schema 版本、文档表/FTS 数量和 FTS 查询。
2. 当前库有效时，使用 SQLite Online Backup API 复制为同目录候选库，再在候选库增量更新。
3. 当前库无效或缺失时，从 Workspace 全量构建候选库。
4. 候选库执行相同完整性检查；任何问题都禁止提升。
5. 提升前将当前有效库保存为 `workspace-search.last-good.db`。
6. 使用同目录原子替换将候选库切换为 `workspace-search.db`。

内容索引不会只信任文件大小和修改时间。schema 1.1 为每个进入 FTS 的文本保存规范化
内容 SHA-256；每次维护都会重新读取允许索引的文本前缀并复核摘要。即使文件被改成相同
长度并恢复原修改时间，摘要变化仍会触发更新。数据库检查还会重新计算 FTS 实际内容摘要，
因此直接篡改 FTS 行但保持 SQLite `quick_check` 正常也会命中
`FTS_CONTENT_HASH_MISMATCH`，候选库不会提升。

候选构建失败不会修改正式数据库。临时候选库及其 WAL/SHM 只属于本次维护，结束后清理。

## 查询回退

`search` 和 `search-status` 会先验证当前库。当前库损坏且 last-good 有效时，查询自动使用
last-good，并返回 `using_fallback=true`。控制平面产生 WARNING
`INDEX_FALLBACK_ACTIVE`；两代都不可用时产生 ERROR `INDEX_UNAVAILABLE`。

下一次 `search-maintain` 会从 Workspace 全量重建当前库。回退是保持搜索可用的临时措施，
不是用旧索引替代修复。

## 命令

```powershell
python scripts/python/workspace_cli.py search-check `
  --database "D:\Workspace\08_Indexes\Search\workspace-search.db"

python scripts/python/workspace_cli.py search-maintain `
  --workspace "D:\Workspace" `
  --database "D:\Workspace\08_Indexes\Search\workspace-search.db" `
  --content `
  --output "D:\Workspace\08_Indexes\Search\search-status.json"
```

## 隐私边界

当前库和 last-good 都位于本地 `08_Indexes/Search`，继承相同访问边界。两者可能包含允许索引
的本地文本内容，因此不应直接发布到 NAS、通知或外部服务。Private、Accounts、
Certificates、secrets 和整个 `08_Indexes` 始终排除。状态报告只保存统计、路径和问题码。

状态 Schema 位于 `search/search-status.schema.json`。
