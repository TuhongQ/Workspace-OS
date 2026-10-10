[CmdletBinding(SupportsShouldProcess)]
param([string]$WorkspacePath = (Join-Path $HOME 'Workspace'), [switch]$Apply)
. (Join-Path $PSScriptRoot 'WorkspaceOS.Common.ps1')
$ArgsList = @('scan-inbox', '--workspace', $WorkspacePath)
if ($Apply -and $PSCmdlet.ShouldProcess($WorkspacePath, '按计划移动 Inbox 文件')) { $ArgsList += '--apply' } else { $ArgsList += '--dry-run' }
Invoke-WorkspaceOSPython -Arguments $ArgsList

