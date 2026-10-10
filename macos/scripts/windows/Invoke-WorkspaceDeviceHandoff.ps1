[CmdletBinding(SupportsShouldProcess)]
param(
    [Parameter(Mandatory)]
    [string]$SourceWorkspace,
    [Parameter(Mandatory)]
    [string]$TargetWorkspace,
    [Parameter(Mandatory)]
    [string]$SourceManifest,
    [Parameter(Mandatory)]
    [string]$TargetManifest,
    [string]$OutputPath
)

. (Join-Path $PSScriptRoot 'WorkspaceOS.Common.ps1')
if ([string]::IsNullOrWhiteSpace($OutputPath)) {
    $OutputPath = Join-Path $TargetWorkspace '08_Indexes\Devices\device-apply-status.json'
}
$Arguments = @(
    'device-apply',
    '--source-workspace', $SourceWorkspace,
    '--target-workspace', $TargetWorkspace,
    '--source-manifest', $SourceManifest,
    '--target-manifest', $TargetManifest,
    '--output', $OutputPath
)
if ($PSCmdlet.ShouldProcess($TargetWorkspace, 'Copy source-only handoff files with staging and verification')) {
    $Arguments += '--apply'
}
Invoke-WorkspaceOSPython -Arguments $Arguments
