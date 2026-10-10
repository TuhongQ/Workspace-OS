# 旧文件迁移指南

按批次执行：扫描 → 生成清单 → 重复检测 → 版本识别 → 分类建议 → 人工确认 → 复制/移动 → 校验哈希 → 回滚记录 → 决定旧文件后续。默认复制；首批只选一个小目录，保留源盘只读快照。

运行 `migration/legacy-scan.py SOURCE --output plan.csv`，编辑 CSV 中的 destination 和 approved；再运行 `migration/migrate.py plan.csv --workspace TARGET` 预览。确认后追加 `--apply`。只有完成恢复演练和保留期审批后，才由用户在系统外处理旧源文件。

