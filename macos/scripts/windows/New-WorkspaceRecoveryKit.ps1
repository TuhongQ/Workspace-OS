[CmdletBinding(SupportsShouldProcess)]
param(
    [string]$RepositoryPath,
    [string]$WorkspacePath = 'D:\Workspace'
)

. (Join-Path $PSScriptRoot 'WorkspaceOS.Common.ps1')
if (-not $RepositoryPath) {
    $RepositoryPath = (Resolve-Path (Join-Path $PSScriptRoot '..\..')).Path
}
$Destination = Join-Path $WorkspacePath '06_Release\Packages'
$Report = Join-Path $WorkspacePath '08_Indexes\Recovery\latest-recovery-kit.json'
$Restic = Join-Path $WorkspacePath '07_Admin\WorkspaceOS\tools\restic.exe'
$Arguments = @(
    'recovery-kit',
    '--source', $RepositoryPath,
    '--destination', $Destination,
    '--restic-executable', $Restic,
    '--report', $Report
)
if ($PSCmdlet.ShouldProcess($Destination, 'Create or verify Workspace OS portable recovery kit')) {
    $Arguments += '--apply'
}
Invoke-WorkspaceOSPython -Arguments $Arguments
