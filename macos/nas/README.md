# NAS 部署

创建五个独立共享目录：`Workspace`（活跃数据）、`WorkspaceArchive`（只读历史）、`WorkspaceBackup`（备份目标）、`WorkspaceSnapshots`（快照空间/说明）、`WorkspacePrivate`（敏感资料）。先建立用户组和最小权限，再启用快照与备份；不要把 RAID 或同步当备份。

