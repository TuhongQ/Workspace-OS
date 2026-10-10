# 平台边界

各平台独立版本和发布，源码分别位于 android、macos、ipad、windows；shared 仅接收明确共用的协议和资源。

Android 工程从根目录整体迁入 android，Gradle 根仍为工程自身目录；先 cd android。原 releases/APK 路径保留。

Mac 源码包含历史 Windows 脚本，暂不拆分内部依赖。iPad 是能力有限的原生预览版，不运行 Mac Python 服务。

默认不配置自动同步、自动覆盖或自动删除。凭据及签名密钥不入库，QuickConnect 网页不等于 SMB 挂载。
