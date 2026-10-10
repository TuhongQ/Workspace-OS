[CmdletBinding()]
param([string]$WorkspacePath = (Join-Path $HOME 'Workspace'))
. (Join-Path $PSScriptRoot 'WorkspaceOS.Common.ps1')
Invoke-WorkspaceOSPython -Arguments @('audit', '--workspace', $WorkspacePath)

