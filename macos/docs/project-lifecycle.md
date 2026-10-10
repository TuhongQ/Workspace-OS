# 项目生命周期

固定状态：INBOX → PLANNING → ACTIVE → REVIEW → RELEASED → ARCHIVED。BLOCKED 和 PAUSED 可从执行阶段进入并在原因解除后返回；禁止从 INBOX 直接标记 RELEASED。

项目先按空间分开：工作项目位于 `01_Projects/Work`，生活项目位于 `01_Projects/Personal`；两个空间各自使用 `Active`、`Paused`、`Completed` 状态目录。

每次状态切换更新 `STATUS.md`、README 的当前任务/下一步、负责人和日期。RELEASED 需具备验收结果、变更记录、校验和与发布清单；ARCHIVED 需确认合同保留期、源码可构建、外部链接和备份状态。归档是移动到只读历史区，不是删除。
