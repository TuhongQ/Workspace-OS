# 多设备同步

Windows 与 Mac 可本地同步当前项目、Knowledge、AI Prompts、Release 和必要的小体积素材。iPhone 只同步 `00_Inbox/Mobile`、当前项目文档、Knowledge、Prompts、Release 成品和预览文件。

默认不同步全部视频原素材、proxies、模型、大型数据集和编译缓存。每个目录只能有一个同步主通道：例如电脑↔NAS；不要再让 iCloud/OneDrive同步同一物理目录。对“云端优化存储”关闭关键目录的按需下载，离线前检查文件已落地。冲突文件先移入 ToSort，比较内容后人工合并；iPhone 上传由每周 Inbox 审核消化。

任何 Windows ↔ Mac 主设备切换都应使用 [可验证的跨设备交接](device-handoff.md)：
复制前清单必须没有目标端独有文件、冲突或未验证内容；复制后两端库存摘要完全一致并签发
`verified` 收据，才允许切换主工作设备。Workspace OS 不自动执行复制或覆盖。
