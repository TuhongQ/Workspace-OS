[CmdletBinding(SupportsShouldProcess)]
param(
    [Parameter(Mandatory)]
    [string]$Archive,
    [Parameter(Mandatory)]
    [string]$TargetWorkspace,
    [Parameter(Mandatory)]
    [string]$TargetDeviceId,
    [string]$OutputPath
)

. (Join-Path $PSScriptRoot 'WorkspaceOS.Common.ps1')
if ([string]::IsNullOrWhiteSpace($OutputPath)) {
    $OutputPath = Join-Path $TargetWorkspace '08_Indexes\Devices\device-bundle-import.json'
}
$Arguments = @(
    'device-bundle-import',
    $Archive,
    '--target-workspace', $TargetWorkspace,
    '--target-device-id', $TargetDeviceId,
    '--output', $OutputPath
)
if ($PSCmdlet.ShouldProcess($TargetWorkspace, 'Import verified offline bundle without overwrite')) {
    $Arguments += '--apply'
}
Invoke-WorkspaceOSPython -Arguments $Arguments
