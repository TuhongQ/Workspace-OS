[CmdletBinding()]
param(
    [string]$NasPath = 'W:\',
    [Parameter(Mandatory)]
    [string]$OutputPath
)

$ErrorActionPreference = 'Stop'
$Timer = [Diagnostics.Stopwatch]::StartNew()
$Available = Test-Path -LiteralPath $NasPath -PathType Container
$MarkerValid = $false
if ($Available) {
    $MarkerValid = Test-Path `
        -LiteralPath (Join-Path $NasPath '.workspace-os.json') `
        -PathType Leaf
}
$Timer.Stop()
$Status = [ordered]@{
    schema_version = '1.0'
    generated_at = [DateTime]::UtcNow.ToString('o')
    status = if ($Available) { 'available' } else { 'unavailable' }
    marker_valid = $MarkerValid
    duration_ms = [int]$Timer.ElapsedMilliseconds
}
$OutputDirectory = Split-Path -Parent $OutputPath
New-Item -ItemType Directory -Force -Path $OutputDirectory | Out-Null
$Status | ConvertTo-Json -Depth 3 |
    Set-Content -Encoding UTF8 -LiteralPath $OutputPath
