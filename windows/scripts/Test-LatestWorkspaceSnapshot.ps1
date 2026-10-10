[CmdletBinding()]
param(
    [string]$WorkspacePath = 'D:\Workspace',
    [string]$SnapshotPath = 'D:\WorkspaceSnapshots',
    [string]$Output
)
. (Join-Path $PSScriptRoot 'WorkspaceOS.Common.ps1')
if ([string]::IsNullOrWhiteSpace($Output)) {
    $Output = Join-Path $WorkspacePath '08_Indexes\BackupVerification\latest-snapshot-verification.json'
}
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
if (-not $ResolvedLatest.StartsWith(
    $ResolvedSnapshotRoot + [IO.Path]::DirectorySeparatorChar,
    [StringComparison]::OrdinalIgnoreCase
)) {
    throw "Latest snapshot is outside the configured snapshot root: $ResolvedLatest"
}
Invoke-WorkspaceOSPython -Arguments @('verify-snapshot', $ResolvedLatest, '--output', $Output)
