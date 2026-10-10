[CmdletBinding()]
param([Parameter(Mandatory = $true)][string]$SnapshotPath)
. (Join-Path $PSScriptRoot 'WorkspaceOS.Common.ps1')
Invoke-WorkspaceOSPython -Arguments @('verify-snapshot', $SnapshotPath)
