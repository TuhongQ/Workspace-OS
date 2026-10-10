[CmdletBinding()]
param(
    [Parameter(Mandatory)]
    [string]$SourceManifest,
    [Parameter(Mandatory)]
    [string]$TargetManifest,
    [Parameter(Mandatory)]
    [string]$OutputPath
)

. (Join-Path $PSScriptRoot 'WorkspaceOS.Common.ps1')
Invoke-WorkspaceOSPython -Arguments @(
    'device-receipt', $SourceManifest, $TargetManifest, '--output', $OutputPath
)
