[CmdletBinding()]
param(
    [string]$WorkspacePath = 'D:\Workspace',
    [string]$SnapshotPath = 'D:\WorkspaceSnapshots',
    [string]$RestoreRoot = 'D:\WorkspaceRestoreTests\Automated',
    [int]$Samples = 16,
    [int]$MaxFileMb = 16,
    [int]$MaxTotalMb = 128
)

. (Join-Path $PSScriptRoot 'WorkspaceOS.Common.ps1')
$StatusPath = Join-Path $WorkspacePath '07_Admin\WorkspaceOS\backup-status.json'
if (-not (Test-Path -LiteralPath $StatusPath -PathType Leaf)) {
    throw "Backup status is missing: $StatusPath"
}
$Status = Get-Content -Raw -Encoding UTF8 -LiteralPath $StatusPath | ConvertFrom-Json
$LatestSnapshot = [string]$Status.last_snapshot
if ([string]::IsNullOrWhiteSpace($LatestSnapshot)) {
    throw 'Backup status does not identify a latest snapshot.'
}
$ResolvedSnapshotRoot = (Resolve-Path -LiteralPath $SnapshotPath).Path
$ResolvedLatest = (Resolve-Path -LiteralPath $LatestSnapshot).Path
if (-not $ResolvedLatest.StartsWith($ResolvedSnapshotRoot + [IO.Path]::DirectorySeparatorChar, [StringComparison]::OrdinalIgnoreCase)) {
    throw "Latest snapshot is outside the configured snapshot root: $ResolvedLatest"
}
$Output = Join-Path $WorkspacePath '08_Indexes\RecoveryDrills\latest-restore-drill.json'
Invoke-WorkspaceOSPython -Arguments @(
    'restore-drill',
    '--workspace', $WorkspacePath,
    '--snapshot', $ResolvedLatest,
    '--restore-root', $RestoreRoot,
    '--samples', "$Samples",
    '--max-file-mb', "$MaxFileMb",
    '--max-total-mb', "$MaxTotalMb",
    '--output', $Output
)
