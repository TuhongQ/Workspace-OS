# 本地搜索与索引

开放 JSON 索引仍是可迁移交换格式。日常搜索使用标准库 SQLite FTS5 数据库：

```powershell
python scripts/python/workspace_cli.py search-maintain --workspace "D:\Workspace" --content
python scripts/python/workspace_cli.py search-check --database "D:\Workspace\08_Indexes\Search\workspace-search.db"
python scripts/python/workspace_cli.py search "恢复演练" --database "D:\Workspace\08_Indexes\Search\workspace-search.db"
.\scripts\windows\Search-Workspace.ps1 "TC862" -Project "HUAWEI/TC862"
```

维护流程先从当前有效索引生成同目录候选库，在候选库内增量更新并完成 SQLite
`quick_check`、必需表、文档计数和 FTS 遍历检查，最后才原子切换。旧的有效索引同时保留为
`workspace-search.last-good.db`；当前库损坏时查询自动回退，维护流程则从事实来源完整重建。
候选构建失败不会覆盖仍可用的当前库。状态写入
`08_Indexes/Search/search-status.json`，格式见
[`search-status.schema.json`](search-status.schema.json)。

增量更新根据文件大小、修改时间和内容模式判断是否需要重读。`--content`
只读取受支持的本地文本格式，每个文件默认最多 1 MiB。Private、Accounts、Certificates、
secrets、开发缓存和整个派生区 `08_Indexes` 不会进入索引。

不带 `--content` 时只构建文件名、路径和元数据索引。原始文件始终是事实来源；SQLite 与 JSON
都是可删除重建的派生索引。

完整的故障模式、隐私边界与恢复流程见
[`docs/search-reliability.md`](../docs/search-reliability.md)。
