[CmdletBinding(SupportsShouldProcess)]
param(
    [string]$WorkspacePath = 'D:\Workspace',
    [int]$KeepLatest = 3,
    [int]$Daily = 7,
    [int]$Weekly = 8,
    [int]$Monthly = 6
)

. (Join-Path $PSScriptRoot 'WorkspaceOS.Common.ps1')
$Destination = Join-Path $WorkspacePath '06_Release\Packages'
$RecoveryIndexes = Join-Path $WorkspacePath '08_Indexes\Recovery'
$Arguments = @(
    'recovery-kit-retention',
    '--destination', $Destination,
    '--keep-latest', "$KeepLatest",
    '--daily', "$Daily",
    '--weekly', "$Weekly",
    '--monthly', "$Monthly",
    '--protect-report', (Join-Path $RecoveryIndexes 'latest-recovery-kit.json'),
    '--protect-report', (Join-Path $RecoveryIndexes 'latest-portable-recovery-kit.json'),
    '--output', (Join-Path $RecoveryIndexes 'recovery-kit-retention.json')
)
if ($PSCmdlet.ShouldProcess($Destination, 'Move expired recovery-kit pairs to recoverable trash')) {
    $Arguments += '--apply'
}
Invoke-WorkspaceOSPython -Arguments $Arguments
