[CmdletBinding(SupportsShouldProcess)]
param(
    [Parameter(Mandatory)]
    [string]$Destination,
    [Parameter(Mandatory)]
    [string]$Label,
    [switch]$ConfirmDistinctPhysicalMedia
)

. (Join-Path $PSScriptRoot 'WorkspaceOS.Common.ps1')
$Arguments = @(
    'backup-media-init',
    '--destination', $Destination,
    '--label', $Label
)
if ($ConfirmDistinctPhysicalMedia) {
    $Arguments += '--confirm-distinct-physical-media'
}
if ($PSCmdlet.ShouldProcess($Destination, 'Create a non-destructive Workspace OS backup-media marker')) {
    $Arguments += '--apply'
}
Invoke-WorkspaceOSPython -Arguments $Arguments
