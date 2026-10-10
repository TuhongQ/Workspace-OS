# 可验证的跨设备交接

## 原则

设备清单和交接收据提供只读门禁。可选事务执行器只复制门禁确认的 `source-only` 文件，
永不覆盖或删除目标文件；默认仍是预览，只有显式 `--apply` 才执行。

默认作用域为：

- `00_Inbox/Mobile`
- `02_Knowledge`
- `04_AI`
- `06_Release`
- `09_Templates`

活动项目必须通过重复的 `--include` 显式加入。`08_Indexes`、开发缓存和
`_WorkspaceOS_Trash` 永不进入清单。

## 三阶段门禁

### 1. 两端分别生成清单

Windows：

```powershell
.\scripts\windows\New-WorkspaceDeviceManifest.ps1 `
  -WorkspacePath "D:\Workspace" `
  -DeviceId "windows-main"
```

macOS：

```bash
./scripts/macos/generate-device-manifest.sh \
  "$HOME/Workspace" "macbook-main" \
  "$HOME/Workspace/08_Indexes/Devices/macbook-main.json"
```

清单只包含设备 ID、相对路径、大小、修改时间和 SHA-256，不包含文件正文、密码或绝对路径。

### 2. 复制前生成门禁计划

```powershell
python scripts/python/workspace_cli.py device-compare `
  windows.json macbook.json `
  --output device-sync-status.json
```

源端独有文件可以进入复制计划，但以下任一情况都会得到 `blocked`：

- 目标端存在源端没有的文件。
- 同一路径内容哈希不同。
- 两端作用域或 Workspace 实例不同。
- 存在超限文件、符号链接或读取失败，无法完整验证。
- 存在 Windows/macOS 可能视为同名的大小写或 Unicode 名称碰撞。
- 两份清单来自同一个设备 ID。

### 3. 可选：执行 source-only 事务复制

当源和目标 Workspace 能同时挂载到本机时，可先预览：

```powershell
.\scripts\windows\Invoke-WorkspaceDeviceHandoff.ps1 `
  -SourceWorkspace "D:\Workspace" `
  -TargetWorkspace "E:\Workspace" `
  -SourceManifest windows.json `
  -TargetManifest macbook.json `
  -WhatIf
```

确认后移除 `-WhatIf`。执行器会：

1. 重新生成两端清单，任一端在计划后变化即阻断。
2. 再次执行冲突、目标独有文件、作用域、实例和跨平台名称门禁。
3. 将全部 source-only 文件复制到目标端 `08_Indexes/Devices/HandoffStaging` 并回读 SHA-256。
4. 提交前再次复扫两端；目标路径存在或父目录是符号链接时拒绝写入。
5. 使用同卷原子重命名提交，随后重新生成目标清单并签发完全一致收据。
6. 进程内失败自动回滚；电源中断留下的事务日志会在下次执行前安全回滚。

中断恢复只会移动哈希仍与事务日志相符的文件。若目标文件在中断后被修改，系统停止并要求
人工检查，不会把新内容当作旧事务回滚。
dry-run 发现中断事务时只报告 `INTERRUPTED_TRANSACTION_PENDING`，不会执行回滚；只有显式
`--apply` 才授权恢复旧事务并继续新的交接。

macOS 使用：

```bash
./scripts/macos/apply-device-handoff.sh \
  /Volumes/SourceWorkspace "$HOME/Workspace" \
  source.json target.json device-apply-status.json --apply
```

### 4. 复制后签发收据

使用外部工具复制时，仍必须选择不删除、不覆盖冲突的模式。复制完成后重新生成两端清单，再执行：

```powershell
python scripts/python/workspace_cli.py device-receipt `
  windows-after.json macbook-after.json `
  --output device-sync-status.json
```

只有作用域、文件集合、大小和每个文件 SHA-256 全部一致时，状态才是 `verified`，
`safe_to_switch_primary_device` 才为 `true`。门禁计划的 `ready` 只表示可以安全开始单向复制，
不表示已经可以切换主工作设备。

## 隐私和防篡改

每份清单包含规范化库存摘要 `inventory_sha256`。加载清单时会重新计算摘要；清单被手工修改、
截断或混入不同库存后比较立即失败。跨设备清单属于派生元数据，存放在各设备本地
`08_Indexes/Devices`，不会自动加入同步作用域。

开放格式 Schema 位于 `search/device-manifest.schema.json`、
`search/device-handoff-receipt.schema.json` 和 `search/device-apply-status.schema.json`，
第三方工具无需依赖 Workspace OS 程序即可验证结构。
