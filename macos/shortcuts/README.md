# iPhone 快捷指令

以下四个快捷指令都以“文件 App 可见的 NAS/云端单向上传目录”为落点，不直接整理正式目录。若 SMB 不稳定，可先保存到唯一云入口，再由电脑单向同步到 `00_Inbox/Mobile`。

1. **文件发送到 Workspace Inbox**：接收共享文件 → 询问项目名（可选）→ 当前日期格式化 `yyyy-MM-dd` → 重命名为 `日期_原名` → 保存到 `00_Inbox/Mobile/Files` → 追加一行到 `upload-log.csv`。
2. **图片发送到素材库 Inbox**：接收图片 → 保留原格式/EXIF → 询问项目或“待分类” → 保存到 `00_Inbox/Mobile/Images/日期_原名` → 写日志。
3. **视频发送到视频素材 Inbox**：接收媒体 → 获取文件大小并二次确认（建议蜂窝网络禁用）→ 保存到 `00_Inbox/Mobile/Video`，不转码、不覆盖 → 写日志。
4. **快速创建项目笔记**：询问项目名、类型和一句话目标 → 生成 Markdown（日期、状态 INBOX、设备、待办）→ 保存到 `00_Inbox/Mobile/Notes`。

所有“保存文件”动作关闭“覆盖已有文件”；同名时加入当前时间 `HHmmss`。快捷指令不包含 NAS 密码，凭据由文件 App/系统钥匙串管理。变量表见 `variables.example.json`。

