# 可验证的离线设备交接包

当两台设备不能同时挂载时，可以把经过校验的 Workspace 内容封装成离线 ZIP。交接包包含用户数据；实际导出必须使用受保护的传输介质（例如启用 BitLocker 的移动盘），并显式确认。

## 导出

```powershell
.\scripts\windows\Export-WorkspaceDeviceBundle.ps1 `
  -Workspace "D:\Workspace" `
  -DeviceId "windows-main" `
  -Destination "E:\Workspace-Handoff" `
  -Include "02_Knowledge","01_Projects\Work\Active\CurrentProject" `
  -ConfirmProtectedTransport
```

默认仅预览。执行实际导出时移除 `-WhatIf`。`-Simulation` 只用于隔离演练，不代表介质已受保护。

## 导入

接收设备先预览：

```powershell
.\scripts\windows\Import-WorkspaceDeviceBundle.ps1 `
  -Archive "E:\Workspace-Handoff\WorkspaceOS-Handoff-windows-main-xxxxxxxxxx.zip" `
  -TargetWorkspace "D:\Workspace" `
  -TargetDeviceId "windows-secondary" `
  -WhatIf
```

确认计划后移除 `-WhatIf`。系统会在导入前校验：

- ZIP 路径安全、成员唯一性和禁止符号链接；
- 设备清单摘要、文件集合、大小和每个文件的 SHA-256；
- Workspace 实例、作用域和目标端当前状态；
- 同路径冲突、目标独有文件和跨平台名称碰撞。

导入只接受 `source-only` 文件，使用本地 staging、提交前复扫和中断恢复。覆盖数与删除数始终为零；任何篡改或冲突都会阻止导入。

`Private`、`Accounts`、`Certificates`、`secrets` 和 `08_Indexes` 不能加入交接作用域。

公开结构定义位于：

- `search/device-handoff-bundle.schema.json`
- `search/device-bundle-import.schema.json`
