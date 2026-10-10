# 架构

系统分为五层：目录规范负责唯一归属；项目模板负责工作上下文；Python 核心提供跨平台确定性操作；PowerShell/Shell 仅做入口适配；NAS、同步和备份负责可用性与恢复。

数据流为 `设备入口 → 00_Inbox → 分类计划 → 人工确认 → 唯一归属目录 → 索引/审计 → Release/Archive → 快照与异地备份`。Markdown、JSON、CSV 和 SHA-256 都是开放格式，避免五年后被单一产品锁定。

安全模型：默认只读或 dry-run；创建不覆盖；移动显式授权并留回滚；无永久删除；AI 默认 metadata-only；Private 永不进 Git。JSON 索引未来可迁移至 SQLite，文件本体不受影响。

