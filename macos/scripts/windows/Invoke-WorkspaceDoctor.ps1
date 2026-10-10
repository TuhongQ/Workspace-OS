[CmdletBinding()]
param(
    [string]$WorkspacePath = 'D:\Workspace',
    [string]$SnapshotPath = 'D:\WorkspaceSnapshots',
    [string]$NasPath = 'W:\',
    [string]$Output = 'D:\Workspace\08_Indexes\Health\workspace-health.json'
)
. (Join-Path $PSScriptRoot 'WorkspaceOS.Common.ps1')
Invoke-WorkspaceOSPython -Arguments @(
    'doctor', '--workspace', $WorkspacePath,
    '--snapshots', $SnapshotPath,
    '--nas', $NasPath,
    '--output', $Output
)
