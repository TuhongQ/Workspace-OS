[CmdletBinding(SupportsShouldProcess)]
param([string]$WorkspacePath = (Join-Path $HOME 'Workspace'))
. (Join-Path $PSScriptRoot 'WorkspaceOS.Common.ps1')
$ArgsList = @('init', '--path', $WorkspacePath)
if (-not $PSCmdlet.ShouldProcess($WorkspacePath, '初始化 Workspace OS')) { $ArgsList += '--dry-run' }
Invoke-WorkspaceOSPython -Arguments $ArgsList

