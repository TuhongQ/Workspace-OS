# 渐进迁移

默认扫描和复制，不移动、不删除、不覆盖。先运行 `legacy-scan.py` 生成 CSV，人工填写 `destination` 并把 `approved` 改为 `yes`，再用 `migrate.py` 预览；显式 `--apply` 才复制。每次执行生成 JSON 回滚记录（复制模式的回滚含目标隔离建议，不自动删除）。

