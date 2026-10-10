# Workspace OS 设计基准

Workspace OS 不替代磁盘阵列，而是把多设备、NAS 和知识库组织为可验证的数字资产控制平面。

## 已吸收的成熟实践

- TrueNAS：只读时间点、恢复时优先克隆/隔离而非原地回滚、快照与复制分层、定期 scrub、容量与任务告警。
- Synology Hyper Backup：多版本、增量备份和自动轮换。
- Borg/restic：内容去重、加密仓库、完整性检查、GFS 保留、默认 dry-run，以及清理前软删除。

## Workspace OS 的实现原则

1. 首个基线完整保留；日常策略只能显式排除可重建缓存，并永久记录排除项。
2. 快照先进入临时目录，生成清单并验证后才原子提交。
3. 恢复必须进入全新隔离目录，执行前后均做 SHA-256 校验。
4. 保留策略默认预览，淘汰快照先进入可恢复回收区。
5. 本地快照与 NAS 加密增量仓库并存，避免单一格式或单一设备成为唯一恢复路径。
6. 加密仓库启用前必须存在独立的离线恢复密钥；不创建只能由当前电脑解密的“伪安全”备份。
7. 磁盘密集任务错峰运行，健康报告统一汇总容量、备份时效、NAS 与异常状态。

## 2026 复核来源

- [TrueNAS 快照文档](https://www.truenas.com/docs/core/13.0/coretutorials/storage/snapshots/)建议恢复文件时优先克隆快照，而不是直接回滚；Workspace OS 对应为“恢复到全新隔离目录”。
- [TrueNAS 复制任务](https://www.truenas.com/docs/scale/26/dataprotection/replication/)区分本地与远端复制；Workspace OS 的恢复就绪度因此不会把同卷快照算作独立介质。
- [TrueNAS 告警设置](https://www.truenas.com/docs/scale/26/systemsettings/alertssettingsservicescreen/)覆盖快照、复制、scrub 与任务失败；Workspace OS 对应为统一告警、任务遥测和去重通知。
- [restic 仓库检查](https://restic.readthedocs.io/en/stable/045_working_with_repos.html)要求通过 `check` 证明仓库结构可用；仅安装 restic 或仅存在仓库目录不会计入异机备份。
- [restic 恢复文档](https://restic.readthedocs.io/en/stable/050_restore.html)支持先 dry-run 并恢复到指定目标；Workspace OS 进一步默认拒绝覆盖已有恢复目标。
