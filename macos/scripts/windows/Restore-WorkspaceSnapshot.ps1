[CmdletBinding(SupportsShouldProcess)]
param(
    [Parameter(Mandatory = $true)][string]$SnapshotPath,
    [Parameter(Mandatory = $true)][string]$Destination
)
. (Join-Path $PSScriptRoot 'WorkspaceOS.Common.ps1')
$ArgsList = @('restore', $SnapshotPath, '--destination', $Destination)
if ($PSCmdlet.ShouldProcess($Destination, "从快照恢复到全新隔离目录")) { $ArgsList += '--apply' }
Invoke-WorkspaceOSPython -Arguments $ArgsList
