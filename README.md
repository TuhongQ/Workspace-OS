# Workspace OS

跨平台 Workspace 与 NAS 工作区工具总仓库。各平台独立版本、独立发布；仓库现已统一命名为 Workspace-OS。

## 平台入口

| 平台 | 源码 | 下载 | 状态 |
|---|---|---|---|
| Android | [android/](android/) | [0.5.4 APK](releases/WorkspaceOS-Nexus-Mobile-0.5.4-release.apk) | Android 8+ |
| macOS | [macos/](macos/) | [2.0.6 SystemLog 修正版](https://github.com/TuhongQ/Workspace-OS/releases/tag/macos-2.0.6-systemlog-20261010) | Apple Silicon，macOS 13+，未 Apple 公证 |
| iPad | [ipad/](ipad/) | [1.0.0 预览版](https://github.com/TuhongQ/Workspace-OS/releases/tag/ipad-v1.0.0-preview.1) | iPadOS 16.5+，TrollStore 安装与 NAS 授权待真机验证 |
| Windows | [Windows 源码](windows/) | [2.2.0 安装包](https://github.com/TuhongQ/Workspace-OS/releases/tag/windows-2.2.0) | Windows x64；需要 WebView2 Runtime |

## 工程与构建

- Android 工程整体迁入 android/，先 cd android，再运行 Gradle。原签名配置及忽略规则保留。
- macos/ 保留 macOS 桌面发布源码及已有共用模块，详见 [Mac 安装指南](docs/installation/macos.md)。
- ipad/ 为原生 SwiftUI 预览版，执行 cd ipad && bash build.sh。
- windows/ 包含 Windows PowerShell 脚本、WPF/WebView2 集成主程序和启动器源码；Python 共用核心与模板仍位于 macos/scripts/python 和 macos/templates，以保持现有相对路径兼容。
- releases/ 保留 Android 历史安装包；桌面安装包通过 GitHub Releases 发布。

默认不配置自动同步、自动覆盖或自动删除。跨平台系统日志约定为工作区相对路径 09_System/SystemLog/；iPad 预览版仅有应用内活动记录，不宣称实现系统日志写入。

请勿提交个人工作区、NAS 数据、凭据、签名私钥、运行时配置或个人日志。示例 NAS 地址需按自己的部署修改。

[跨平台约定](docs/architecture/platforms.md) · [发布规范](docs/releases/README.md) · [迁移记录](docs/releases/2026-10-10.md)
