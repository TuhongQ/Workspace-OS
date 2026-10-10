# macOS 控制中心

macOS 版控制中心与 Windows 版共用 Workspace OS 2.0 核心，提供同一组日常功能：

- 初始化工作区、收件箱预览和确认整理。
- 搜索、更新全文索引。
- 快照预览、创建快照。
- 系统健康、安全检查、提醒与告警、恢复就绪度。
- 选择快照恢复到新目录、Finder 打开工作区、打开使用说明。
- 配置 NAS 挂载路径并保存到当前 macOS 用户目录。
- 打开本地网页版，进行电脑/NAS 左右对比、上传、下载和任务进度查看。

## 便携版启动

1. 解压 `WorkspaceOS-2.0.0-Portable-macOS-*.zip`。
2. 把 `Workspace OS.app` 拖入“应用程序”，或直接双击。
3. 选择本机工作区；默认是 `~/Workspace`。
4. 点击“NAS 设置”，填写 Finder 已挂载的共享目录，例如 `/Volumes/Workspace`。

设置保存在：

`~/Library/Application Support/WorkspaceOS/control-center-settings.json`

安装包不包含用户资料、账号、密码、Token、NAS 数据或个人设置。

## 运行要求

- macOS 12 或更高版本。
- Python 3.11 或更高版本，并包含 Tk 图形组件；建议使用 python.org 官方 macOS Python。
- NAS 必须先在 Finder 中连接并挂载到 `/Volumes` 下。

此便携包在 Windows 构建，因此没有 Apple Developer ID 签名或公证。首次启动如被阻止，可在 Finder 中按住 Control 点击应用并选择“打开”。

包内的 `BUILD-STANDALONE.command` 可在 Mac 本机使用 PyInstaller 生成不依赖外部 Python 的独立 `.app`。正式对外分发前仍需使用自己的 Apple Developer ID 完成签名和公证。
