[CmdletBinding(SupportsShouldProcess)]
param([string]$WorkspacePath = (Join-Path $HOME 'Workspace'))
Write-Warning '安全策略禁止脚本删除 Workspace。本命令仅说明手工卸载步骤。'
Write-Output "1. 备份并验证：$WorkspacePath"
Write-Output '2. 保留 .workspace-os.json 与日志。'
Write-Output '3. 确认同步已停止后，由管理员手工移动到隔离目录。'

