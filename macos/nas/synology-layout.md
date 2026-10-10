# Synology 示例

在控制面板创建五个共享文件夹；若存储池支持，使用 Btrfs。Snapshot Replication 对 Workspace 每小时快照；Hyper Backup 每日备份到外接盘/另一 NAS并启用客户端加密。Universal Search 只索引非 Private 范围。使用专用 `svc_backup` 账户，不授予 DSM 管理权限。

