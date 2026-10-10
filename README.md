# Workspace OS

跨平台 Workspace 与 NAS 工作区工具总仓库。各平台独立版本、独立发布；仓库 URL 暂时保留 Workspace-OS-Android。

## 平台入口

| 平台 | 源码 | 下载 | 状态 |
|---|---|---|---|
| Android | [android/](android/) | [0.5.4 APK](releases/WorkspaceOS-Nexus-Mobile-0.5.4-release.apk) | Android 8+ |
| macOS | [macos/](macos/) | [2.0.6 SystemLog 修正版](https://github.com/TuhongQ/Workspace-OS-Android/releases/tag/macos-2.0.6-systemlog-20261010) | Apple Silicon，macOS13+，未 Apple 公证 |
| iPad | [ipad/](ipad/) | [1.0.0 预览版](https://github.com/TuhongQ/Workspace-OS-Android/releases/tag/ipad-v1.0.0-preview.1) | iPadOS16.5+，TrollStore 安装与 NAS 授权待真机验证 |
| Windows | [接入说明](windows/) | 暂无独立发布 | 历史 Windows 脚本暂留 macos/scripts/windows |

## 工程与构建

- Android 工程整体迁入 android/，先 cd android，再运行 Gradle。原签名配置及忽略规则保留。
- macos/ 保留桌面发布源码及已有共用模块，详见 [Mac 安装指南](docs/installation/macos.md)。
- ipad/ 为原生 SwiftUI 预览版，执行 cd ipad && bash build.sh。
- windows/、shared/ 为接入规范，尚未机械搬迁有依赖的共享模块。
- releases/ 保留历史 APK；后续安装包只上传 GitHub Releases。

默认不配置自动同步、自动覆盖或自动删除。跨平台系统日志约定为工作区相对路径 09_System/SystemLog/；iPad 预览版仅有应用内活动记录，不宣称实现系统日志写入。

请勿提交个人工作区、NAS 数据、凭据、签名私钥、运行时配置或个人日志。示例 NAS 地址需按自己的部署修改。

[跨平台约定](docs/architecture/platforms.md) · [发布规范](docs/releases/README.md) · [迁移记录](docs/releases/2026-10-10.md)
