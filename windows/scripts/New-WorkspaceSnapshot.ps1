[CmdletBinding(SupportsShouldProcess)]
param(
    [string]$WorkspacePath = 'D:\Workspace',
    [Parameter(Mandatory = $true)][string]$Destination,
    [string]$Name,
    [switch]$ExcludeRebuildableCache
)
. (Join-Path $PSScriptRoot 'WorkspaceOS.Common.ps1')
$ArgsList = @('snapshot', '--workspace', $WorkspacePath, '--destination', $Destination)
if ($Name) { $ArgsList += @('--name', $Name) }
if ($ExcludeRebuildableCache) { $ArgsList += '--exclude-rebuildable-cache' }
if ($PSCmdlet.ShouldProcess($WorkspacePath, "创建快照到 $Destination")) { $ArgsList += '--apply' }
Invoke-WorkspaceOSPython -Arguments $ArgsList
