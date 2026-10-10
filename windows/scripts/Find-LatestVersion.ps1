[CmdletBinding()]
param([Parameter(Mandatory)][string]$Path)
. (Join-Path $PSScriptRoot 'WorkspaceOS.Common.ps1')
Invoke-WorkspaceOSPython -Arguments @('latest', $Path)

