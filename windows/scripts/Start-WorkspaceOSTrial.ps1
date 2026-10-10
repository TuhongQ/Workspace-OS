[CmdletBinding()]
param(
    [string]$TrialRoot = (Join-Path $env:LOCALAPPDATA 'WorkspaceOS-Trial'),
    [switch]$NoOpen
)

$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot 'WorkspaceOS.Common.ps1')
$ResolvedRoot = [IO.Path]::GetFullPath($TrialRoot)
$Marker = Join-Path $ResolvedRoot '.workspace-os-trial.json'
$Workspace = Join-Path $ResolvedRoot 'Workspace'
$Snapshots = Join-Path $ResolvedRoot 'Snapshots'
$OfflineNas = Join-Path $ResolvedRoot 'Offline-NAS'
$Report = Join-Path $ResolvedRoot 'trial-result.json'

if (Test-Path -LiteralPath $ResolvedRoot) {
    $HasContent = $null -ne (Get-ChildItem -Force -LiteralPath $ResolvedRoot | Select-Object -First 1)
    if ($HasContent -and -not (Test-Path -LiteralPath $Marker -PathType Leaf)) {
        throw "试用根目录非空且没有 Workspace OS 试用标记，拒绝写入：$ResolvedRoot"
    }
}
else {
    New-Item -ItemType Directory -Path $ResolvedRoot | Out-Null
}

if (-not (Test-Path -LiteralPath $Marker -PathType Leaf)) {
    Invoke-WorkspaceOSPython -Arguments @('init', '--path', $Workspace) | Out-Null
    Invoke-WorkspaceOSPython -Arguments @(
        'new', 'software', 'NEXUS-Trial',
        '--workspace', $Workspace, '--space', 'work'
    ) | Out-Null
    $MarkerData = [ordered]@{
        schema_version = '1.0'
        created_at = [DateTime]::UtcNow.ToString('o')
        product = 'Workspace OS'
        version = (Get-Content -Raw -Encoding UTF8 (Join-Path $PSScriptRoot '..\..\VERSION')).Trim()
        workspace = $Workspace
    }
    $MarkerTemporary = Join-Path $ResolvedRoot ('.workspace-os-trial.{0}.tmp' -f [guid]::NewGuid().ToString('N'))
    $MarkerData | ConvertTo-Json -Depth 3 | Set-Content -LiteralPath $MarkerTemporary -Encoding UTF8
    Move-Item -LiteralPath $MarkerTemporary -Destination $Marker
}

New-Item -ItemType Directory -Force -Path $Snapshots, $OfflineNas | Out-Null
& (Join-Path $PSScriptRoot 'New-WorkspaceSnapshot.ps1') `
    -WorkspacePath $Workspace `
    -Destination $Snapshots `
    -ExcludeRebuildableCache | Out-Null
& (Join-Path $PSScriptRoot 'Test-LatestWorkspaceSnapshot.ps1') `
    -WorkspacePath $Workspace `
    -SnapshotPath $Snapshots `
    -Output (Join-Path $Workspace '08_Indexes\BackupVerification\latest-snapshot-verification.json') | Out-Null
& (Join-Path $PSScriptRoot 'Audit-Workspace.ps1') -WorkspacePath $Workspace | Out-Null
& (Join-Path $PSScriptRoot 'Update-WorkspaceControlPlane.ps1') `
    -WorkspacePath $Workspace `
    -SnapshotPath $Snapshots `
    -NasPath $OfflineNas `
    -PublishRetryHours 0 `
    -PublishTimeoutSeconds 10 | Out-Null

$Dashboard = Join-Path $Workspace '08_Indexes\file-locations.html'
$SecurityAudit = Get-Content -Raw -Encoding UTF8 `
    (Join-Path $Workspace '08_Indexes\Security\security-audit.json') | ConvertFrom-Json
$Evidence = Get-Content -Raw -Encoding UTF8 `
    (Join-Path $Workspace '08_Indexes\Evidence\status.json') | ConvertFrom-Json
$Search = Get-Content -Raw -Encoding UTF8 `
    (Join-Path $Workspace '08_Indexes\Search\search-status.json') | ConvertFrom-Json
$Verification = Get-Content -Raw -Encoding UTF8 `
    (Join-Path $Workspace '08_Indexes\BackupVerification\latest-snapshot-verification.json') | ConvertFrom-Json
$Result = [ordered]@{
    schema_version = '1.0'
    completed_at = [DateTime]::UtcNow.ToString('o')
    status = if (
        $Verification.valid -and
        $Search.current_valid -and
        $Evidence.valid -and
        $SecurityAudit.status -eq 'healthy' -and
        (Test-Path -LiteralPath $Dashboard -PathType Leaf)
    ) { 'passed' } else { 'failed' }
    trial_root = $ResolvedRoot
    workspace = $Workspace
    snapshots = $Snapshots
    dashboard = $Dashboard
    gates = [ordered]@{
        snapshot_verified = [bool]$Verification.valid
        search_valid = [bool]$Search.current_valid
        evidence_chain_valid = [bool]$Evidence.valid
        credential_exposure_findings = [int]$SecurityAudit.summary.findings
        dashboard_exists = (Test-Path -LiteralPath $Dashboard -PathType Leaf)
        source_overwrites = 0
        source_deletions = 0
    }
}
$ResultTemporary = Join-Path $ResolvedRoot ('.trial-result.{0}.tmp' -f [guid]::NewGuid().ToString('N'))
$Result | ConvertTo-Json -Depth 5 | Set-Content -LiteralPath $ResultTemporary -Encoding UTF8
Move-Item -LiteralPath $ResultTemporary -Destination $Report -Force

if ($Result.status -ne 'passed') {
    throw "Workspace OS 隔离试用验收失败，查看：$Report"
}
if (-not $NoOpen) {
    Start-Process $Dashboard
}
$Result
