[CmdletBinding(SupportsShouldProcess)]
param([Parameter(Mandatory)][ValidateSet('software','ai','video','work')][string]$Type,
      [Parameter(Mandatory)][string]$Name, [string]$WorkspacePath = (Join-Path $HOME 'Workspace'))
. (Join-Path $PSScriptRoot 'WorkspaceOS.Common.ps1')
$ArgsList = @('new', $Type, $Name, '--workspace', $WorkspacePath)
if (-not $PSCmdlet.ShouldProcess($Name, "创建 $Type 项目")) { $ArgsList += '--dry-run' }
Invoke-WorkspaceOSPython -Arguments $ArgsList

