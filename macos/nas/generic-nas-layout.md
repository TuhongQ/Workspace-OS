# 通用 NAS 布局

建议卷启用校验/快照能力；共享目录不要互相嵌套。客户端只挂载 Workspace 与按需只读 Archive；Backup、Snapshots 不给日常账号写权限，Private 单独加密并限制管理员也使用独立审计账户。路径映射记录在设备配置，不硬编码进脚本。

