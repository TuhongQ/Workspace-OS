[CmdletBinding(SupportsShouldProcess)]
param(
    [string]$Destination = 'D:\Workspace\07_Admin\WorkspaceOS\tools',
    [switch]$Replace
)
Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$Api = 'https://api.github.com/repos/restic/restic/releases/latest'
$Headers = @{ 'User-Agent' = 'WorkspaceOS-Restic-Installer' }
$Release = Invoke-RestMethod -Headers $Headers -Uri $Api
$Version = "$($Release.tag_name)".TrimStart('v')
$AssetName = "restic_${Version}_windows_amd64.zip"
$Asset = $Release.assets | Where-Object name -eq $AssetName | Select-Object -First 1
$Sums = $Release.assets | Where-Object name -eq 'SHA256SUMS' | Select-Object -First 1
if (-not $Asset -or -not $Sums) { throw 'Official restic release assets are incomplete.' }

$Target = Join-Path $Destination 'restic.exe'
$Metadata = Join-Path $Destination 'restic-install.json'
if ((Test-Path -LiteralPath $Target) -and -not $Replace) {
    & $Target version
    return
}
if (-not $PSCmdlet.ShouldProcess($Target, "Install verified restic $Version")) { return }

$TempRoot = [IO.Path]::GetFullPath([IO.Path]::GetTempPath())
$Temp = Join-Path $TempRoot ("workspaceos-restic-" + [guid]::NewGuid().ToString('N'))
New-Item -ItemType Directory -Path $Temp | Out-Null
try {
    $Archive = Join-Path $Temp $AssetName
    $SumsPath = Join-Path $Temp 'SHA256SUMS'
    Invoke-WebRequest -Headers $Headers -Uri $Asset.browser_download_url -OutFile $Archive
    Invoke-WebRequest -Headers $Headers -Uri $Sums.browser_download_url -OutFile $SumsPath
    $Line = Get-Content -LiteralPath $SumsPath | Where-Object { $_ -match ("\s" + [regex]::Escape($AssetName) + "$") } | Select-Object -First 1
    if (-not $Line -or $Line -notmatch '^([a-fA-F0-9]{64})\s+') { throw 'Unable to find the asset checksum.' }
    $Expected = $Matches[1].ToUpperInvariant()
    $Actual = (Get-FileHash -Algorithm SHA256 -LiteralPath $Archive).Hash
    if ($Actual -ne $Expected) { throw "SHA-256 mismatch for $AssetName" }
    $Extracted = Join-Path $Temp 'extracted'
    Expand-Archive -LiteralPath $Archive -DestinationPath $Extracted
    $Binary = Get-ChildItem -LiteralPath $Extracted -Filter '*.exe' | Select-Object -First 1
    if (-not $Binary) { throw 'The restic archive did not contain an executable.' }
    New-Item -ItemType Directory -Force -Path $Destination | Out-Null
    Copy-Item -LiteralPath $Binary.FullName -Destination $Target -Force
    @{
        name = 'restic'
        version = $Version
        installed_at = [DateTimeOffset]::UtcNow.ToString('o')
        source = $Asset.browser_download_url
        sha256 = (Get-FileHash -Algorithm SHA256 -LiteralPath $Target).Hash
        archive_sha256 = $Actual
    } | ConvertTo-Json | Set-Content -Encoding UTF8 -LiteralPath $Metadata
    & $Target version
}
finally {
    $ResolvedTemp = [IO.Path]::GetFullPath($Temp)
    if ($ResolvedTemp.StartsWith($TempRoot, [StringComparison]::OrdinalIgnoreCase) -and (Test-Path -LiteralPath $ResolvedTemp)) {
        Remove-Item -LiteralPath $ResolvedTemp -Recurse -Force
    }
}
