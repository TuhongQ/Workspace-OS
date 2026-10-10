# 便携恢复工具包

便携恢复工具包用于主程序目录损坏、换机或跨设备安装。它只包含 Workspace OS 程序、
文档、模板、示例配置、测试和可选的公开程序二进制，不包含 Workspace 用户数据、
密码、Token、私钥或 restic 仓库密码。

## 生成

默认只预览：

```powershell
python scripts/python/workspace_cli.py recovery-kit `
  --source "D:\CodeX\Workspace OS 2.0" `
  --destination "D:\Workspace\06_Release\Packages"
```

显式添加 `--apply` 才生成。Windows 完整包可附带已经校验安装的 restic：

```powershell
.\scripts\windows\New-WorkspaceRecoveryKit.ps1
```

同日同名包已经存在时不会覆盖；只有 ZIP 内部清单和外层 SHA-256 都通过才返回
`existing_verified`。无效同名包会阻止生成。

## 双层校验

1. 外层 `.sha256` 证明 ZIP 传输前后内容一致。
2. ZIP 内 `RECOVERY-KIT-MANIFEST.json` 和 `SHA256SUMS.txt` 记录每个文件的大小与哈希。
3. `recovery-kit-verify` 会拒绝路径穿越、缺失文件、额外文件、大小或哈希不一致。

```powershell
python scripts/python/workspace_cli.py recovery-kit-verify `
  "D:\Workspace\06_Release\Packages\<恢复包文件名>.zip"
```

## 当前产物

- Windows 完整包：`WorkspaceOS-Recovery-Kit-<版本>-<日期>-<源码指纹>.zip`，含 restic 二进制。
- 跨设备轻量包：`WorkspaceOS-Recovery-Portable-<版本>-<日期>-<源码指纹>.zip`，不含平台二进制。
- NAS 轻量包：位于 `W:\06_Release\Packages`，选择带配套 `.sha256` 的最新 Portable 包。

源码指纹来自实际打包文件的路径与 SHA-256。程序、文档或模板有任何变化都会生成新文件名；
内容完全相同才会幂等复用，避免“同一天验证通过但内容已经过期”。

NAS 端不由 Windows 回读整包哈希，以避免 SMB 阻塞；Mac 或新电脑必须在解压前用旁路
`.sha256` 验证。每周 `WorkspaceOS-WeeklyRecoveryKit` 会创建或重新验证本地完整包。

## 恢复包保留

内容指纹保证新版本不会覆盖旧版本，因此需要独立的生命周期策略。命令默认只预览；
显式添加 `--apply` 后，ZIP 与同名 `.sha256` 会成对移动到
`_WorkspaceOS_Trash/RecoveryKits`，不会永久删除：

```powershell
python scripts/python/workspace_cli.py recovery-kit-retention `
  --destination "D:\Workspace\06_Release\Packages"
python scripts/python/workspace_cli.py recovery-kit-retention `
  --destination "D:\Workspace\06_Release\Packages" --apply
```

默认分别保护完整包和轻量包的最近 3 个版本，并保留 7 个每日桶、8 个每周桶和
6 个月度桶。`--protect-report` 可保护状态报告正在引用的包；同名 `.keep` 文件可手工固定。
缺少校验文件的孤儿包只告警并保留，不会被自动移动。

## 演练原则

始终解压到全新隔离目录，从解压后的 CLI 反向校验原 ZIP，再阅读 `RESTORE-FIRST.md`。
不要把工具包当作用户数据备份，也不要把其中的 restic 程序误认为已经存在可恢复仓库。
验证器还会拒绝绝对路径、路径穿越、反斜杠路径、重复 ZIP 成员、符号链接、加密成员
和不安全的清单相对路径；解压前必须先验证。
