# Workspace OS NEXUS Mobile

本工程已迁入总仓库的 android/。运行下列 Gradle 命令前先 `cd android`；原根目录已有本机 local.properties、keystore.properties 或 keystore/ 的开发者需自行将它们放到此目录，勿提交凭据。历史 APK 下载仍在仓库根 releases/。

Workspace OS 2.0 的原生安卓客户端（Kotlin + Jetpack Compose）。通过 SMB2/3 直连 NAS，适用于局域网或 ZeroTier 虚拟网络；深色 NEXUS 科技风界面，与 Windows/macOS 控制中心及网页看板同一套设计语言。

当前版本：**v0.5.4**（minSdk 26 / targetSdk 35）

## 功能

### NAS 文件管理
- NAS 连接档：多个 NAS 配置随意切换，每个连接的密码用 Android Keystore (AES-GCM) 独立加密保存
- 目录浏览、当前目录搜索、名称/大小/时间排序（目录恒置顶，选择持久化）
- 上传手机文件、新建文件夹、重命名；文件或文件夹左滑删除（含二次确认与递归删除核验）
- 小文件（≤64 MB）应用内预览：图片双指缩放、Markdown 渲染、文本直读；其他格式跳转系统应用
- 同步到手机：断点续传、大小校验、原子提交；完成后出现在「最近同步」卡片，一键打开
- 下载目录可自定义：系统目录选择器授权任意文件夹，镜像 NAS 目录层级写入
- 传输日志自动追加到 NAS 的 `09_System/SystemLog/WorkspaceOS/`，与桌面版 Workspace OS 同一记录体系

### 手机文件管理
- 系统目录授权（SAF）后浏览、搜索、新建、重命名、创建副本、左滑删除
- 文件/文件夹复制到另一手机目录，或递归上传到 NAS，保留子目录结构

### 传输体验
- 后台任务中心：聚合进度、字节数、百分比，支持中途取消
- 慢速 NAS 下界面不阻塞；连接状态自动降级与友好错误提示（登录失败/超时/找不到共享等）

## 构建

环境：JDK 17、Android SDK Platform 35、Build Tools 36、Gradle 8.7（wrapper 自带）。

```powershell
# 调试包
./gradlew.bat :app:lintDebug :app:assembleDebug

# 正式签名包（需要本地签名配置，见下）
./gradlew.bat :app:assembleRelease
```

构建产物：`app/build/outputs/apk/...`（已被 .gitignore 排除）。

### 正式版签名（每台构建机本地准备，不进仓库）

在 `android/` 下创建 `keystore.properties`（已被 .gitignore 排除）：

```properties
storeFile=../keystore/workspaceos-release.keystore
storePassword=你的密钥库口令
keyAlias=workspaceos
keyPassword=你的密钥口令
```

并把密钥库文件放到 `android/keystore/`。缺少该文件时 Release 构建自动回退为无签名，Debug 构建不受影响。

## 技术栈

- Kotlin 2.0.21、Jetpack Compose (Material 3)、单 Activity 架构 + ViewModel/StateFlow
- [smbj](https://github.com/hierynomus/smbj) 0.13.0（纯 Java SMB2/3 客户端）
- DocumentFile + DocumentsContract（SAF 手机文件访问，单次批量查询）
- R8 压缩（Release），smbj/BouncyCastle 反射保留规则见 `app/proguard-rules.pro`

## 源码结构

```
app/src/main/java/com/workspaceos/mobile/
  MainActivity.kt          # 全部 Compose 界面（深色 NEXUS 主题）
  WorkspaceViewModel.kt    # UI 状态、任务编排、预览与打开
  SmbRepository.kt         # SMB 浏览/上传/下载/重命名/日志
  LocalFileRepository.kt   # 手机目录浏览/复制/删除/副本
  SecureSettings.kt        # 多连接档与 Keystore 加密存储
```

## 后续计划

- WorkManager 前台服务：进程重启后的长任务恢复与通知栏进度
- NAS/手机双栏差异比较与冲突策略
- 应用商店发布渠道与自动更新
