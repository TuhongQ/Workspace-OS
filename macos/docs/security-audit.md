# 安全暴露审计

`security-audit` 在本机检查 Workspace 中高置信度的凭据暴露、私钥材料、带密码的
URI、敏感文件名和指向工作区之外的符号链接或目录联接。

```powershell
python scripts/python/workspace_cli.py security-audit `
  --workspace "D:\Workspace" `
  --output "D:\Workspace\08_Indexes\Security\security-audit.json"
```

日常控制平面刷新会自动运行。结果进入统一告警、NEXUS 和证据链。

## 隐私边界

- 报告只保存规则编号、相对路径、行号、严重度和修复建议。
- 命中的 Token、密码、私钥片段和内容指纹均不会写入 JSON、Markdown、告警或通知。
- `Private`、`Accounts`、`Certificates`、`secrets` 下的文件内容不扫描。
- `08_Indexes`、开发缓存和恢复包回收区不扫描，避免派生报告反复触发。
- 超过 2 MiB 或非文本文件默认不读取内容，但敏感文件名仍会检查。

这项检查不能证明凭据一定有效，也不能替代凭据提供器、终端防护、代码托管平台的
Secret Scanning 或密钥轮换。

## 显式例外

只有确认测试夹具中的值是合成数据后，才复制
`config/security-audit-ignore.example.json` 到：

`D:\Workspace\07_Admin\WorkspaceOS\security-audit-ignore.json`

例外按相对路径 glob 和规则编号匹配。不要用全局 `*` 掩盖真实风险；原因字段应说明
审查依据。配置文件位于派生系统目录，不进入内容扫描。

## 发现后的处理

1. 不要把疑似密钥复制到工单、聊天或日志。
2. 在对应服务端立即撤销或轮换凭据。
3. 将程序改为从 Windows Credential Manager、环境变量或专用 Secret Manager 读取。
4. 删除历史暴露前先保留必要证据；版本库历史需按平台流程清理。
5. 重新运行审计，确认报告恢复为 `healthy`。
