# Windows 源码与发布

## Windows 源码

Windows 专属源码现在直接放在本目录：

- `scripts/`：最新 Windows PowerShell 控制中心、NAS 文件对比/传输、系统维护、恢复和启动脚本。此批源码同步自仓库当前主线快照 `2397701f2c3c7c6eb265d975e5986ce1591ff6aa`；历史副本仍保留在 `macos/scripts/windows/`，以免破坏原有相对路径。
- `native/WorkspaceOS.IntegratedHost/`：WPF/WebView2 集成桌面主程序源码，对应已构建的 NEXUS 2.2.0。
- `launcher/`：桌面启动器、命令行入口与 NEXUS 图标。

Python 核心和工作区模板是跨平台共享依赖，仍位于 `macos/scripts/python/` 和 `macos/templates/`；这两个目录不是 macOS 专属代码。Windows 2.2.0 的完整构建源码快照另见 [版本源码归档](releases/2.2.0/README.md)。

## Windows 安装包

Windows x64 集成安装包通过 GitHub Releases 分发，不提交到源码树。当前已准备 `WorkspaceOS Windows 2.2.0` 草稿 Release，包含安装程序和 SHA-256；草稿尚未公开发布。安装程序自带 .NET 8 与 Python，首次运行若缺少 WebView2 Runtime 会尝试安装。可选桌面快捷方式，提供开始菜单和卸载入口。

此安装包未签名，Windows 可能显示未知发布者提示。现有本机安装冒烟验证有记录，但此次未重新进行干净电脑安装或 NAS 实时传输测试。

## 安全边界

源码不包含个人 Workspace 文件、运行时配置、账号密码、凭据、签名私钥或个人日志。NAS UNC 地址只作为可编辑的部署默认值；安装后应在控制中心填写本机实际路径。Release 发布前需复核版本、校验值和平台标记。
