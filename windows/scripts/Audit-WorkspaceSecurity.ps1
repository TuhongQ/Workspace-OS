[CmdletBinding()]
param(
    [string]$WorkspacePath = 'D:\Workspace',
    [string]$ConfigPath = '',
    [ValidateRange(64, 16384)]
    [int]$MaxFileKb = 2048,
    [ValidateRange(1, 10000)]
    [int]$MaxFindings = 500
)

$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot 'WorkspaceOS.Common.ps1')

$Output = Join-Path $WorkspacePath '08_Indexes\Security\security-audit.json'
$Arguments = @(
    'security-audit',
    '--workspace', $WorkspacePath,
    '--max-file-kb', [string]$MaxFileKb,
    '--max-findings', [string]$MaxFindings,
    '--output', $Output
)
if (-not [string]::IsNullOrWhiteSpace($ConfigPath)) {
    $Arguments += @('--config', $ConfigPath)
}

Invoke-WorkspaceOSPython -Arguments $Arguments
