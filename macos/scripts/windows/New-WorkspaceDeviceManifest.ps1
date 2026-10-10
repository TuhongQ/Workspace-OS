[CmdletBinding()]
param(
    [string]$WorkspacePath = 'D:\Workspace',
    [string]$DeviceId = $env:COMPUTERNAME,
    [string]$OutputPath = '',
    [string[]]$Include = @(),
    [int]$MaxFileMB = 512
)

. (Join-Path $PSScriptRoot 'WorkspaceOS.Common.ps1')
if ([string]::IsNullOrWhiteSpace($DeviceId)) { $DeviceId = 'windows-local' }
if ([string]::IsNullOrWhiteSpace($OutputPath)) {
    $OutputPath = Join-Path $WorkspacePath '08_Indexes\Devices\local-device-manifest.json'
}
$Arguments = @(
    'device-manifest',
    '--workspace', $WorkspacePath,
    '--device-id', $DeviceId,
    '--max-file-mb', "$MaxFileMB",
    '--output', $OutputPath
)
foreach ($Scope in $Include) {
    $Arguments += @('--include', $Scope)
}
Invoke-WorkspaceOSPython -Arguments $Arguments
