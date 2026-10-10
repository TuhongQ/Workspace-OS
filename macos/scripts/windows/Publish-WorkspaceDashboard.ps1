[CmdletBinding()]
param(
    [string]$WorkspacePath = 'D:\Workspace',
    [string]$NasPath = 'W:\'
)

$ErrorActionPreference = 'Stop'
$Dashboard = Join-Path $WorkspacePath '08_Indexes\file-locations.html'
$DashboardJson = [IO.Path]::ChangeExtension($Dashboard, '.json')
$RecoveryLog = Join-Path $WorkspacePath '08_Indexes\Alerts\nas-publish-recovery.json'

if (-not (Test-Path -LiteralPath $Dashboard -PathType Leaf)) {
    throw "Dashboard HTML does not exist: $Dashboard"
}
if (-not (Test-Path -LiteralPath $DashboardJson -PathType Leaf)) {
    throw "Dashboard JSON does not exist: $DashboardJson"
}
if (-not (Test-Path -LiteralPath $NasPath -PathType Container)) {
    throw "NAS path is unavailable: $NasPath"
}

$NasIndexes = Join-Path $NasPath '08_Indexes'
New-Item -ItemType Directory -Force -Path $NasIndexes | Out-Null
$LocalCompressedJson = Join-Path `
    (Split-Path -Parent $DashboardJson) `
    ('.file-locations.json.{0}.gz.tmp' -f $PID)
$LocalDescriptor = Join-Path `
    (Split-Path -Parent $DashboardJson) `
    ('.file-locations.json.{0}.descriptor.tmp' -f $PID)

function Publish-AtomicFile {
    param(
        [Parameter(Mandatory)]
        [string]$Source,
        [Parameter(Mandatory)]
        [string]$Destination
    )
    $Temporary = Join-Path `
        (Split-Path -Parent $Destination) `
        ('.{0}.{1}.partial' -f (Split-Path -Leaf $Destination), $PID)
    if (Test-Path -LiteralPath $Temporary -PathType Leaf) {
        throw "Publisher staging file already exists: $Temporary"
    }
    [IO.File]::Copy($Source, $Temporary, $false)
    Move-Item -LiteralPath $Temporary -Destination $Destination -Force
}

try {
    # A killed publisher can leave only process-scoped staging files. Recover
    # stale ones to NAS trash before the next publish; never permanently delete.
    $RecoveredPartials = @()
    $StaleBefore = [DateTime]::UtcNow.AddHours(-6)
    $StalePartials = @(
        Get-ChildItem -LiteralPath $NasIndexes -Force -File -Filter '.file-locations.*.partial' |
            Where-Object { $_.LastWriteTimeUtc -lt $StaleBefore }
    )
    if ($StalePartials.Count) {
        $PartialTrash = Join-Path `
            $NasIndexes `
            ('_WorkspaceOS_Trash\NexusPublish\{0}-{1}' -f [DateTime]::Now.ToString('yyyyMMdd-HHmmss'), [guid]::NewGuid().ToString('N').Substring(0, 8))
        New-Item -ItemType Directory -Force -Path $PartialTrash | Out-Null
        foreach ($Partial in $StalePartials) {
            $RecoveredPath = Join-Path $PartialTrash $Partial.Name
            Move-Item -LiteralPath $Partial.FullName -Destination $RecoveredPath
            $RecoveredPartials += [ordered]@{
                source = $Partial.FullName
                trash = $RecoveredPath
                bytes = $Partial.Length
                last_write_time = $Partial.LastWriteTimeUtc.ToString('o')
            }
        }
    }
    $Recovery = [ordered]@{
        schema_version = '1.0'
        generated_at = [DateTime]::UtcNow.ToString('o')
        destination = $NasIndexes
        stale_after_hours = 6
        moved_count = $RecoveredPartials.Count
        moved = $RecoveredPartials
    }
    $RecoveryTemporary = $RecoveryLog + '.' + [guid]::NewGuid().ToString('N') + '.tmp'
    $Recovery | ConvertTo-Json -Depth 5 |
        Set-Content -Encoding UTF8 -LiteralPath $RecoveryTemporary
    Move-Item -LiteralPath $RecoveryTemporary -Destination $RecoveryLog -Force

    # HTML is self-contained. Publishing the same data again as raw JSON
    # needlessly doubles slow SMB traffic, so NAS receives a gzip payload plus
    # a small descriptor at the legacy JSON path.
    $InputStream = [IO.File]::OpenRead($DashboardJson)
    try {
        $OutputStream = [IO.File]::Create($LocalCompressedJson)
        try {
            $GzipStream = [IO.Compression.GzipStream]::new(
                $OutputStream,
                [IO.Compression.CompressionLevel]::Optimal,
                $false
            )
            try {
                $InputStream.CopyTo($GzipStream)
            }
            finally {
                $GzipStream.Dispose()
            }
        }
        finally {
            $OutputStream.Dispose()
        }
    }
    finally {
        $InputStream.Dispose()
    }

    $SourceJson = Get-Content -Raw -Encoding UTF8 -LiteralPath $DashboardJson | ConvertFrom-Json
    $Descriptor = [ordered]@{
        schema_version = '1.0'
        generated_at = $SourceJson.generated_at
        format = 'gzip'
        payload = 'file-locations.json.gz'
        content_encoding = 'gzip'
        original_bytes = (Get-Item -LiteralPath $DashboardJson).Length
        compressed_bytes = (Get-Item -LiteralPath $LocalCompressedJson).Length
        original_sha256 = (Get-FileHash -LiteralPath $DashboardJson -Algorithm SHA256).Hash.ToLowerInvariant()
    }
    $Descriptor | ConvertTo-Json -Depth 3 |
        Set-Content -Encoding UTF8 -LiteralPath $LocalDescriptor

    # Stage under an exact process-scoped name and switch only complete files.
    # Commit the descriptor last so it never points at an unpublished payload.
    Publish-AtomicFile `
        -Source $LocalCompressedJson `
        -Destination (Join-Path $NasIndexes 'file-locations.json.gz')
    Publish-AtomicFile `
        -Source $Dashboard `
        -Destination (Join-Path $NasIndexes 'file-locations.html')
    Publish-AtomicFile `
        -Source $LocalDescriptor `
        -Destination (Join-Path $NasIndexes 'file-locations.json')
}
finally {
    Remove-Item -LiteralPath $LocalCompressedJson, $LocalDescriptor -Force -ErrorAction SilentlyContinue
}
