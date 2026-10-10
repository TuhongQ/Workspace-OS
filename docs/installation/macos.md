# macOS 安装

在首页选择 Mac 专属 Release，下载 ZIP 与校验文件。要求 Apple Silicon，macOS13+。

退出旧版，解压 ZIP，将 Workspace OS.app 拖入应用程序。ad-hoc签名，未 Apple 公证，不建议关闭系统安全保护。

构建：在 macos/ 执行 `zsh scripts/macos/build-native-app.sh /绝对路径/新的构建目录`；需 Xcode Command Line Tools、Python3.11+、PyInstaller 和带 Tk 的 Python，可通过 WORKSPACE_BUILD_PYTHON 指定解释器。

测试：在 macos/ 执行 `python3 -m unittest discover -s tests -v`。
