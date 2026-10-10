# ACL 与磁盘加密安全态势

Windows 探针读取 `Private`、`Accounts`、`Certificates`、`secrets` 的 ACL 和 Workspace
所在卷的 BitLocker 状态。探针只输出 SID、布尔权限分类和状态码，不保存本机用户名。

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass `
  -File ".\scripts\windows\Audit-WorkspaceSecurityPosture.ps1" `
  -WorkspacePath "D:\Workspace"
```

探针在独立进程中执行，默认 15 秒超时；超时或无权限会生成“证据不可用”警告，而不会
猜测磁盘是否加密。

主要门槛：

- 宽泛主体（Everyone、Authenticated Users、内置 Users）拥有写入权限：ERROR。
- 宽泛主体只有读取权限：WARNING。
- 受保护目录继续继承上级 ACL：WARNING。
- BitLocker 明确未完整加密或保护关闭：ERROR。
- 无法取得可信 BitLocker 状态：WARNING。

审计本身不会自动更改 ACL、所有者或 BitLocker。Workspace OS 另提供显式、默认只预览的
ACL 加固入口；它只处理 `Accounts`、`Certificates`、`Private` 三个固定目录。

先预览：

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass `
  -File ".\scripts\windows\Protect-WorkspaceSensitiveDirectories.ps1" `
  -WorkspacePath "D:\Workspace"
```

确认报告中的 `changes_required` 后显式应用：

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass `
  -File ".\scripts\windows\Protect-WorkspaceSensitiveDirectories.ps1" `
  -WorkspacePath "D:\Workspace" `
  -Apply
```

应用前脚本会先用 `icacls /save /t` 为所有待修改目录生成完整 ACL 备份；备份目录已存在时
拒绝覆盖。目录根阻断继承，仅保留当前 Workspace 用户、SYSTEM、Administrators 完全控制，
现有子项重新继承该边界。任一步骤失败都会停止，应用后还会逐目录自检。

报告保存在 `08_Indexes/Security/acl-hardening.json`，并进入证据链和 NEXUS。脚本拒绝把
报告写到 `08_Indexes/Security` 之外，也拒绝把 ACL 备份放进受保护目录。文件内容、名称和
位置不会改变；报告中的 `content_overwrites` 与 `content_deletions` 必须为 0。

回滚命令随每次备份写入同目录的 `RESTORE.md`。回滚后必须重新运行安全态势审计，不能只
凭当前用户仍能打开目录就判断权限正确。

## 管理员磁盘加密证据

普通权限进程无法读取 BitLocker 状态时，探针会返回 `ADMIN_REQUIRED`，不会猜测磁盘
是否加密。请在“管理员 PowerShell”中一次性导出本机证据：

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass `
  -File ".\scripts\windows\Export-WorkspaceEncryptionEvidence.ps1" `
  -WorkspacePath "D:\Workspace"
```

证据默认写入 `08_Indexes/Security/encryption-evidence.json`。普通权限的日常审计只在
证据不超过 192 小时，且 Workspace 标记 SHA-256 和卷标识哈希均与当前环境一致时采用
它；过期、被复制到另一套 Workspace、来自另一块磁盘或查询状态不完整时都会拒绝。
证据只保留哈希化卷标识和 BitLocker 状态，不包含用户名或恢复密钥，也不会启用、暂停
或修改 BitLocker。
