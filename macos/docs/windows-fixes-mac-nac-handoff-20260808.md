# Workspace OS 2.0：Windows 最新修复与 Mac/NAC 交接要点

更新时间：2026-08-08

## 一、交接结论

Windows 便携版当前的核心方向已经稳定为：本地优先、NAS 可验证、网页负责对比与操作、后台服务负责复制。Mac/NAC 版本应沿用同一套数据模型和安全边界，不要重新设计成“打开 NAS 网页后直接同步”。

当前推荐 Windows 发布包：

`D:\Workspace\06_Release\Packages\PortableVerified\WorkspaceOS-2.0.0-Portable-Windows-19542e55ad.zip`

SHA-256：

`4e820682aadf99d82c1e47483a67265b5a39a72af76dbebe0d4477d7e60e5a54`

发布验证：92 项测试、37 个 Python 文件编译、PowerShell 脚本解析、1,098 个便携包文件清单全部通过。

## 二、最近修复的 Windows Bug

### 1. NAS 地址失效但资源管理器可访问

现象：控制中心保存的旧地址不可访问，但资源管理器可以打开 NAS。

根因：Windows 用户配置中保存了旧 IP，例如 `\\192.168.100.110\Workspace`，实际 NAS 已变为 `\\192.168.1.9\Workspace`。

修复：

- 控制中心检测已保存地址是否可访问。
- 失效时探测 SMB 映射和常用 UNC 入口。
- 找到可用入口后临时回退，并在活动日志中显示原地址和实际地址。
- 用户仍可在“NAS 设置”中保存最终地址。

Mac/NAC 对齐要求：

- 不要只依赖固定 IP。
- 优先使用用户配置的 SMB 挂载点。
- 挂载点失效时提示重新连接，不要把“未挂载”误判为“文件不存在”。

### 2. 网页显示“NAS 空间不可用”

现象：NAS 文件根目录可以扫描，但网页容量卡片显示不可用。

根因：文件元数据缓存为空时，`nas_storage.available=false`，网页把“容量缓存缺失”误显示成“NAS 离线”。

修复：

- 控制中心打开网页时增加 `--refresh-nas-capacity`。
- 文件对比继续使用缓存，避免 SMB 全量扫描卡顿。
- 网页区分“容量待刷新”和“NAS 不可访问”。

Mac/NAC 对齐要求：

- 文件扫描状态和容量状态必须分离。
- NAS 根目录可读但容量 API 失败时，仍允许文件对比。
- UI 状态至少区分 `connected`、`metadata-cached`、`capacity-unavailable`、`offline`。

### 3. “浏览器打开电脑目录”按钮无效并弹窗

现象：浏览器无法可靠打开 `file://` 文件夹链接，部分浏览器会新开页面或弹出无效提示。

根因：浏览器安全策略不允许网页直接调用 Windows 资源管理器。

修复：

- 按钮统一显示为“打开目录”。
- 本机网页服务新增 `/api/open-folder` 和 `/api/open-folder-path`。
- 服务端校验目录必须位于已配置的电脑工作区或 NAS 工作区。
- Windows 使用 `os.startfile()` 调用资源管理器。
- 网页点击时 `preventDefault()`，不再打开网页弹窗或新标签页。
- 旧版 `file://` 链接也会被新模板拦截并转换为资源管理器调用。

Mac/NAC 对齐要求：

- 使用 macOS `open <path>`，不要依赖浏览器打开 `file://`。
- 服务端必须校验路径在本地工作区或已挂载 NAS 内。
- 网页按钮只发本机 IPC/HTTP 请求，不弹新网页。

### 4. 关闭网页后后台服务长期占用

现象：关闭网页后，`dashboard_sync_server.py` 仍在后台运行。

修复：

- 关闭控制中心时立即结束网页服务。
- 网页 30 秒无请求且没有传输任务时自动退出。
- 传输任务运行中不会被误杀。

Mac/NAC 对齐要求：

- 使用应用生命周期管理本地服务。
- 服务必须有空闲回收机制。
- 复制任务运行时服务保持存活，任务完成后允许回收。

### 5. 新包打开旧网页

现象：客户复制新包后，控制中心仍显示旧版网页。

根因：旧逻辑在网页生成失败时回退到工作区里的旧 `08_Indexes/file-locations.html`。

修复：

- 网页模板随便携包一起发布。
- 打开网页时使用包内模板重新生成临时页面。
- 容量刷新失败时只使用同一包模板重试。
- 禁止静默打开工作区旧网页；生成失败直接写入日志并停止。
- 客户必须从新解压目录中的 `WorkspaceOS.cmd` 启动，不能继续使用旧桌面快捷方式。

Mac/NAC 对齐要求：

- 网页模板必须版本化并随程序发布。
- 数据文件和 UI 模板分离。
- 不能在启动失败时静默加载旧缓存页面。
- 页面应显示应用版本和模板版本，方便现场确认是否为新版本。

## 三、当前网页与服务结构

```text
控制中心
  └─ 生成临时 file-locations.html
      └─ 启动 localhost dashboard_sync_server.py
          ├─ /dashboard                 网页 UI
          ├─ /api/health                服务健康检查
          ├─ /api/refresh               刷新电脑/NAS 对比数据
          ├─ /api/sync/jobs             创建和读取传输任务
          ├─ /api/open-folder           打开工作区相对目录
          └─ /api/open-folder-path      打开已验证的绝对目录
```

传输原则：网页只提交用户选择，服务端负责路径校验、清单生成、复制、进度持久化和刷新结果；普通同步不覆盖同名文件，覆盖操作必须由用户明确选择。

## 四、Mac/NAC 实现时必须保留的行为

1. 本地工作区优先，NAS 是集中保存和跨设备访问端。
2. SMB 未挂载时不得把文件状态伪装成“NAS 缺失”。
3. 文件差异、容量状态、NAS 网络状态分开显示。
4. 打开目录调用操作系统文件管理器，不通过浏览器跳转。
5. 所有复制任务显示一个总任务进度，内部文件作为明细，不拆成大量任务卡片。
6. 刷新页面后仍可从任务记录恢复运行中任务状态。
7. 不默认启用双向自动覆盖、自动删除或无人值守同步。
8. 所有跨设备复制先生成清单，发生冲突、目标新增文件或清单过期时阻止覆盖。
9. 日志、操作记录和错误原因应写入 NAS 的交接目录，便于 Windows/Mac 共用。

## 五、Mac/NAC 验收清单

- [ ] SMB 挂载 `smb://192.168.1.9/Workspace` 后识别为 NAS 可用。
- [ ] NAS 容量读取失败时仍能查看文件对比。
- [ ] 点击“打开目录”直接打开 Finder，不弹浏览器页面。
- [ ] 关闭网页后本机后台服务自动回收。
- [ ] 关闭应用后所有子进程都退出。
- [ ] 上传、下载、覆盖任务显示总进度和百分比。
- [ ] 刷新网页后运行中任务仍可恢复显示。
- [ ] 新模板不会回退加载旧 HTML。
- [ ] Python/Swift/原生服务测试通过，并保存验证报告。

## 六、交接文件位置

- Windows 源码：`D:\CodeX\Workspace OS 2.0`
- 网页模板：`templates/location-dashboard.html`
- 网页服务：`scripts/python/dashboard_sync_server.py`
- Windows 控制中心：`scripts/windows/WorkspaceOS-ControlCenter-WPF.ps1`
- 发布验证：`scripts/python/release_verify.py`
- NAS 交接目录：`\\192.168.1.9\Workspace\06_Release\Packages`
- NAS Obsidian 日志：`\\192.168.1.9\Workspace\02_Knowledge\ObsidianVault\01_Daily`
