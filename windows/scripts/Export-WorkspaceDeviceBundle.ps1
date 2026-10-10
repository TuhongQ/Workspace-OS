[CmdletBinding(SupportsShouldProcess)]
param(
    [Parameter(Mandatory)]
    [string]$Workspace,
    [Parameter(Mandatory)]
    [string]$DeviceId,
    [Parameter(Mandatory)]
    [string]$Destination,
    [string[]]$Include = @('01_Projects', '02_Knowledge', '03_Media', '04_Deliverables'),
    [ValidateRange(1, 102400)]
    [int]$MaxFileMB = 512,
    [switch]$ConfirmProtectedTransport,
    [switch]$Simulation,
    [string]$OutputPath
)

. (Join-Path $PSScriptRoot 'WorkspaceOS.Common.ps1')
$Arguments = @(
    'device-bundle-export',
    '--workspace', $Workspace,
    '--device-id', $DeviceId,
    '--destination', $Destination,
    '--max-file-mb', $MaxFileMB
)
foreach ($Scope in $Include) {
    $Arguments += @('--include', $Scope)
}
if ($ConfirmProtectedTransport) {
    $Arguments += '--confirm-protected-transport'
}
if ($Simulation) {
    $Arguments += '--simulation'
}
if (-not [string]::IsNullOrWhiteSpace($OutputPath)) {
    $Arguments += @('--output', $OutputPath)
}
if ($PSCmdlet.ShouldProcess($Destination, 'Export verified offline Workspace device bundle')) {
    $Arguments += '--apply'
}
Invoke-WorkspaceOSPython -Arguments $Arguments
