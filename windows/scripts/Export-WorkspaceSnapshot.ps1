[CmdletBinding(SupportsShouldProcess)]
param(
    [string]$WorkspacePath = 'D:\Workspace',
    [string]$SnapshotPath = 'D:\WorkspaceSnapshots',
    [Parameter(Mandatory)]
    [string]$MediaPath
)

. (Join-Path $PSScriptRoot 'WorkspaceOS.Common.ps1')
$BackupStatus = Join-Path $WorkspacePath '07_Admin\WorkspaceOS\backup-status.json'
if (-not (Test-Path -LiteralPath $BackupStatus -PathType Leaf)) {
    throw "Backup status is missing: $BackupStatus"
}
$Status = Get-Content -Raw -Encoding UTF8 -LiteralPath $BackupStatus | ConvertFrom-Json
$LatestSnapshot = [string]$Status.last_snapshot
if ([string]::IsNullOrWhiteSpace($LatestSnapshot)) {
    throw 'Backup status does not identify a latest snapshot.'
}
$ResolvedRoot = [IO.Path]::GetFullPath($SnapshotPath).TrimEnd('\')
$ResolvedLatest = [IO.Path]::GetFullPath($LatestSnapshot)
if (-not $ResolvedLatest.StartsWith($ResolvedRoot + '\', [StringComparison]::OrdinalIgnoreCase)) {
    throw "Latest snapshot is outside the configured snapshot root: $ResolvedLatest"
}
$Output = Join-Path $WorkspacePath '08_Indexes\Recovery\snapshot-export.json'
$Arguments = @(
    'snapshot-export',
    '--snapshot', $ResolvedLatest,
    '--media', $MediaPath,
    '--output', $Output
)
if ($PSCmdlet.ShouldProcess($MediaPath, 'Export the latest verified snapshot without overwrite')) {
    $Arguments += '--apply'
}
Invoke-WorkspaceOSPython -Arguments $Arguments
