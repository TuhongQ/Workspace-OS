# Workspace OS 2.0.0 首个可用版本

首发包是无用户数据、无凭据的 Windows ZIP。它包含完整命令行、PowerShell 入口、
模板、文档、测试和离线清单。发行包不会自动注册计划任务，也不会改动现有 Workspace。
内部清单与外层 `.sha256` 必须同时通过；验证器拒绝绝对路径、`..` 路径穿越、
反斜杠路径、重复成员、ZIP 符号链接、加密成员和恶意清单相对路径。

## 最安全的试用方式

1. 校验下载目录旁的 `.sha256`。
2. 解压 ZIP。
3. 双击解压后顶层的 `TRY-WORKSPACE-OS.cmd`。

也可以在终端运行底层入口：

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass `
  -File ".\scripts\windows\Start-WorkspaceOSTrial.ps1"
```

默认试用目录是 `%LOCALAPPDATA%\WorkspaceOS-Trial`。入口会拒绝写入没有试用标记的
非空目录，且只在试用根目录内创建 Workspace、快照、离线 NAS 模拟目录和验收报告。

验收门槛：

- 创建一份可校验快照并完成全量回读；
- 当前 SQLite 搜索库有效；
- 控制平面证据链有效；
- 凭据暴露扫描无发现；
- NEXUS 页面成功生成；
- 对既有用户数据覆盖与删除均为 0。

成功后打开 `Workspace\08_Indexes\file-locations.html`，并在试用根目录写入
`trial-result.json`。重复运行会复用带标记的试用目录，不覆盖现有项目。

## 正式初始化

确认试用通过后，可指定一个全新目录：

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass `
  -File ".\scripts\windows\Install-WorkspaceOS.ps1" `
  -WorkspacePath "D:\Workspace"
```

安装入口仅创建缺失目录与模板；同名项目、非空发布目标和恢复目标均有拒绝覆盖门禁。
计划任务、NAS、外置介质和加密异机备份需要单独启用。

## 依赖与已知限制

- Windows 10/11 与 Python 3.11+。
- NEXUS 是本地 HTML 控制台，不需要云端账户。
- 首发包不内置 Python、凭据或用户数据。
- 当前机器的 ACL、BitLocker、NAS 与 3-2-1 状态会如实显示告警，不会为了“绿色”
  状态自动修改权限、启用加密或伪造异地副本。
