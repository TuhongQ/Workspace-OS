[CmdletBinding(SupportsShouldProcess)]
param(
    [Parameter(Mandatory = $true)][string]$Destination,
    [int]$Hourly = 24,
    [int]$Daily = 30,
    [int]$Weekly = 12,
    [int]$Monthly = 12
)
. (Join-Path $PSScriptRoot 'WorkspaceOS.Common.ps1')
$ArgsList = @(
    'retention', '--destination', $Destination,
    '--hourly', "$Hourly", '--daily', "$Daily",
    '--weekly', "$Weekly", '--monthly', "$Monthly"
)
if ($PSCmdlet.ShouldProcess($Destination, 'Move expired snapshots to the recoverable trash folder')) { $ArgsList += '--apply' }
Invoke-WorkspaceOSPython -Arguments $ArgsList
