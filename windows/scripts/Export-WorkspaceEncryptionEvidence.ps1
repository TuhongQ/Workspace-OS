[CmdletBinding()]
param(
    [string]$WorkspacePath = 'D:\Workspace',
    [string]$OutputPath
)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

if ($env:OS -ne 'Windows_NT') {
    throw 'BitLocker evidence export is supported only on Windows.'
}
$Identity = [Security.Principal.WindowsIdentity]::GetCurrent()
$Principal = New-Object Security.Principal.WindowsPrincipal($Identity)
if (-not $Principal.IsInRole(
    [Security.Principal.WindowsBuiltInRole]::Administrator
)) {
    throw 'Run this evidence export from an Administrator PowerShell.'
}

$WorkspaceRoot = [IO.Path]::GetFullPath($WorkspacePath).TrimEnd(
    [IO.Path]::DirectorySeparatorChar
)
$Marker = Join-Path $WorkspaceRoot '.workspace-os.json'
if (-not (Test-Path -LiteralPath $Marker -PathType Leaf)) {
    throw "The target is not an initialized Workspace OS root: $WorkspaceRoot"
}
$Output = if ([string]::IsNullOrWhiteSpace($OutputPath)) {
    Join-Path $WorkspaceRoot '08_Indexes\Security\encryption-evidence.json'
}
else {
    [IO.Path]::GetFullPath($OutputPath)
}
$AllowedOutputRoot = [IO.Path]::GetFullPath(
    (Join-Path $WorkspaceRoot '08_Indexes\Security')
).TrimEnd([IO.Path]::DirectorySeparatorChar)
if (-not $Output.StartsWith(
    $AllowedOutputRoot + [IO.Path]::DirectorySeparatorChar,
    [StringComparison]::OrdinalIgnoreCase
)) {
    throw "Encryption evidence must stay under 08_Indexes\Security: $Output"
}

$Root = [IO.Path]::GetPathRoot($WorkspaceRoot)
$DriveLetter = $Root.TrimEnd('\').TrimEnd(':')
$DiskVolume = Get-Volume -DriveLetter $DriveLetter -ErrorAction Stop
$BitLocker = Get-BitLockerVolume -MountPoint $Root -ErrorAction Stop
if (-not $BitLocker) {
    throw 'The BitLocker query returned no volume evidence.'
}

function Get-Sha256Text {
    param([Parameter(Mandatory)][string]$Value)
    $Hasher = [Security.Cryptography.SHA256]::Create()
    try {
        return (
            $Hasher.ComputeHash(
                [Text.Encoding]::UTF8.GetBytes($Value.ToLowerInvariant())
            ) |
            ForEach-Object { $_.ToString('x2') }
        ) -join ''
    }
    finally {
        $Hasher.Dispose()
    }
}

$Report = [ordered]@{
    schema_version = '1.0'
    generated_at = [DateTime]::UtcNow.ToString('o')
    platform = 'windows'
    source = 'elevated-bitlocker'
    privacy_mode = 'hashed-volume-id-no-user-identities'
    workspace_marker_sha256 = (
        Get-FileHash -Algorithm SHA256 -LiteralPath $Marker
    ).Hash.ToLowerInvariant()
    mount_point = $Root
    filesystem = [string]$DiskVolume.FileSystem
    volume_id_hash = Get-Sha256Text -Value ([string]$DiskVolume.UniqueId)
    query_status = 'ok'
    volume_status = [string]$BitLocker.VolumeStatus
    protection_status = [string]$BitLocker.ProtectionStatus
    encryption_percentage = [int]$BitLocker.EncryptionPercentage
    encryption_method = [string]$BitLocker.EncryptionMethod
}

$Directory = Split-Path -Parent $Output
New-Item -ItemType Directory -Force -Path $Directory | Out-Null
$Temporary = Join-Path $Directory (
    '.encryption-evidence.{0}.tmp' -f [guid]::NewGuid().ToString('N')
)
try {
    $Report | ConvertTo-Json -Depth 5 |
        Set-Content -LiteralPath $Temporary -Encoding UTF8
    Move-Item -LiteralPath $Temporary -Destination $Output -Force
}
finally {
    Remove-Item -LiteralPath $Temporary -Force -ErrorAction SilentlyContinue
}
$Report | ConvertTo-Json -Depth 5


