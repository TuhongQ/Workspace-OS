# Workspace OS iPad 1.0.0 Preview

目标：iPad Pro M1 12.9 英寸，iPadOS16.5。原生 SwiftUI 预览版，不是 Mac Python 后台的完整移植。

[下载 IPA 和 SHA-256](https://github.com/TuhongQ/Workspace-OS-Android/releases/tag/ipad-v1.0.0-preview.1)

## 安装与能力

将 IPA 传到 iPad，分享到已安装的 TrollStore 安装。这不是 App Store 分发包。

- 提供本地目录、浏览搜索、中文别名、NAS 系统目录授权、应用内活动记录、QuickConnect 网页入口。
- NAS 先在系统“文件”连接服务器，再在应用选择 Workspace。SMB 提供器是否支持目录授权仍待真机确认；不支持时使用系统“文件”管理 NAS。
- 未实现应用内文件预览、上传下载、目录对比、看板生成、快照和 Mac 后台。
- 不保存密码、不修改 NAS 文件；授权本次启动有效。卸载前先另存应用内重要资料。

## 构建

需 macOS、完整 Xcode 及 iOS SDK：

```sh
cd ipad
bash build.sh
bash build.sh iphonesimulator
```

每次使用新的 build-* 目录。包标识 local.workspaceos.ipad，版本1.0.0（1），最低iOS16.5，arm64，ad-hoc签名。

## 验证边界

此次重新核对现有 IPA 摘要、arm64/iOS16.5 元数据及 App 严格签名。此前在 iOS26.5 iPad 模拟器安装启动并检查画面，不等于iPadOS16.5真机通过。TrollStore安装、启动、SMB授权待用户实测。上传已有预览产物，不代表新增功能或正式版验收。
