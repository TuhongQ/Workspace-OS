[CmdletBinding()]
param(
    [string]$WorkspacePath = 'D:\Workspace',
    [Parameter(Mandatory)]
    [string]$OutputPath,
    [string]$EncryptionEvidencePath,
    [ValidateRange(1, 720)]
    [int]$EncryptionEvidenceMaxAgeHours = 192,
    [switch]$CachedEvidenceOnly
)

$ErrorActionPreference = 'Stop'
$WorkspaceRoot = [IO.Path]::GetFullPath($WorkspacePath).TrimEnd('\')
$Marker = Join-Path $WorkspaceRoot '.workspace-os.json'
$EncryptionEvidence = if ([string]::IsNullOrWhiteSpace($EncryptionEvidencePath)) {
    Join-Path $WorkspaceRoot '08_Indexes\Security\encryption-evidence.json'
}
else {
    [IO.Path]::GetFullPath($EncryptionEvidencePath)
}
$CurrentUserSid = [Security.Principal.WindowsIdentity]::GetCurrent().User.Value
$RelativePaths = @(
    '07_Admin\Private',
    '07_Admin\Accounts',
    '07_Admin\Certificates',
    '07_Admin\secrets'
)
$WriteMask = 2 -bor 4 -bor 16 -bor 64 -bor 256 -bor 65536 -bor 262144 -bor 524288
$ReadMask = 1 -bor 8 -bor 128 -bor 131072
$ProtectedPaths = @()

foreach ($Relative in $RelativePaths) {
    $Path = Join-Path $WorkspaceRoot $Relative
    $Item = [ordered]@{
        relative = ($Relative -replace '\\', '/')
        exists = (Test-Path -LiteralPath $Path -PathType Container)
        acl_query_status = 'not-applicable'
        owner_sid = $null
        owner_is_current_user = $false
        inheritance_protected = $null
        access = @()
    }
    if ($Item.exists) {
        try {
            $Acl = Get-Acl -LiteralPath $Path -ErrorAction Stop
            $OwnerSid = try {
                (New-Object Security.Principal.NTAccount($Acl.Owner)).
                    Translate([Security.Principal.SecurityIdentifier]).Value
            }
            catch { $null }
            $Rules = @()
            foreach ($Rule in $Acl.Access) {
                $Sid = try {
                    $Rule.IdentityReference.
                        Translate([Security.Principal.SecurityIdentifier]).Value
                }
                catch { $null }
                if (-not $Sid) { continue }
                $Rights = [int64]$Rule.FileSystemRights
                $Rules += [ordered]@{
                    sid = $Sid
                    access_type = [string]$Rule.AccessControlType
                    inherited = [bool]$Rule.IsInherited
                    can_read = (($Rights -band $ReadMask) -ne 0)
                    can_write = (($Rights -band $WriteMask) -ne 0)
                }
            }
            $Item.acl_query_status = 'ok'
            $Item.owner_sid = $OwnerSid
            $Item.owner_is_current_user = ($OwnerSid -eq $CurrentUserSid)
            $Item.inheritance_protected = [bool]$Acl.AreAccessRulesProtected
            $Item.access = $Rules
        }
        catch {
            $Item.acl_query_status = 'failed'
        }
    }
    $ProtectedPaths += $Item
}

$Root = [IO.Path]::GetPathRoot($WorkspaceRoot)
$Volume = [ordered]@{
    mount_point = $Root
    filesystem = $null
    query_status = 'unavailable'
    query_code = 'QUERY_NOT_RUN'
    volume_status = $null
    protection_status = $null
    encryption_percentage = $null
    encryption_method = $null
    evidence_source = 'none'
    evidence_generated_at = $null
    evidence_age_hours = $null
    live_query_code = 'QUERY_NOT_RUN'
    cached_evidence_status = 'not-checked'
    volume_id_hash = $null
}
$DiskVolume = $null
try {
    $DriveLetter = $Root.TrimEnd('\').TrimEnd(':')
    $DiskVolume = Get-Volume -DriveLetter $DriveLetter -ErrorAction Stop
    $Volume.filesystem = [string]$DiskVolume.FileSystem
    if (-not [string]::IsNullOrWhiteSpace([string]$DiskVolume.UniqueId)) {
        $Bytes = [Text.Encoding]::UTF8.GetBytes(
            ([string]$DiskVolume.UniqueId).ToLowerInvariant()
        )
        $Hasher = [Security.Cryptography.SHA256]::Create()
        try {
            $Volume.volume_id_hash = (
                $Hasher.ComputeHash($Bytes) |
                ForEach-Object { $_.ToString('x2') }
            ) -join ''
        }
        finally {
            $Hasher.Dispose()
        }
    }
}
catch {}
$CurrentIdentity = [Security.Principal.WindowsIdentity]::GetCurrent()
$CurrentPrincipal = New-Object Security.Principal.WindowsPrincipal(
    $CurrentIdentity
)
$IsAdministrator = $CurrentPrincipal.IsInRole(
    [Security.Principal.WindowsBuiltInRole]::Administrator
)
if ($CachedEvidenceOnly) {
    $Volume.live_query_code = 'CACHED_ONLY'
    $Volume.query_code = 'CACHED_ONLY'
}
else {
try {
    $BitLocker = Get-BitLockerVolume -MountPoint $Root -ErrorAction Stop
    if (-not $BitLocker) {
        throw 'BitLocker query returned no volume evidence.'
    }
    $Volume.query_status = 'ok'
    $Volume.query_code = 'OK'
    $Volume.live_query_code = 'OK'
    $Volume.evidence_source = 'live-bitlocker'
    $Volume.evidence_generated_at = [DateTime]::UtcNow.ToString('o')
    $Volume.evidence_age_hours = 0
    $Volume.volume_status = [string]$BitLocker.VolumeStatus
    $Volume.protection_status = [string]$BitLocker.ProtectionStatus
    $Volume.encryption_percentage = [int]$BitLocker.EncryptionPercentage
    $Volume.encryption_method = [string]$BitLocker.EncryptionMethod
}
catch {
    $Volume.query_status = 'unavailable'
    $Volume.live_query_code = if (-not $IsAdministrator) {
        'ADMIN_REQUIRED'
    }
    elseif (
        $_.Exception.Message -match '拒绝访问|Access.*denied|0x80041003'
    ) {
        'ACCESS_DENIED'
    }
    else {
        'BITLOCKER_QUERY_FAILED'
    }
    $Volume.query_code = $Volume.live_query_code
}
}

if ($Volume.query_status -ne 'ok') {
    if (-not (Test-Path -LiteralPath $EncryptionEvidence -PathType Leaf)) {
        $Volume.cached_evidence_status = 'missing'
    }
    else {
        try {
            $Cached = Get-Content -Raw -Encoding UTF8 -LiteralPath $EncryptionEvidence |
                ConvertFrom-Json -ErrorAction Stop
            $Generated = [DateTimeOffset]::Parse(
                [string]$Cached.generated_at,
                [Globalization.CultureInfo]::InvariantCulture
            )
            $AgeHours = (
                [DateTimeOffset]::UtcNow - $Generated.ToUniversalTime()
            ).TotalHours
            $MarkerHash = if (Test-Path -LiteralPath $Marker -PathType Leaf) {
                (Get-FileHash -Algorithm SHA256 -LiteralPath $Marker).Hash.ToLowerInvariant()
            }
            else {
                $null
            }
            if ([string]$Cached.schema_version -ne '1.0') {
                $Volume.cached_evidence_status = 'schema-invalid'
            }
            elseif (
                $AgeHours -lt -0.1 -or
                $AgeHours -gt $EncryptionEvidenceMaxAgeHours
            ) {
                $Volume.cached_evidence_status = 'stale'
            }
            elseif (
                [string]::IsNullOrWhiteSpace($MarkerHash) -or
                [string]$Cached.workspace_marker_sha256 -ne $MarkerHash
            ) {
                $Volume.cached_evidence_status = 'workspace-mismatch'
            }
            elseif (
                [string]::IsNullOrWhiteSpace([string]$Volume.volume_id_hash) -or
                [string]$Cached.volume_id_hash -ne [string]$Volume.volume_id_hash
            ) {
                $Volume.cached_evidence_status = 'volume-mismatch'
            }
            elseif ([string]$Cached.query_status -ne 'ok') {
                $Volume.cached_evidence_status = 'query-invalid'
            }
            else {
                $Volume.query_status = 'ok'
                $Volume.query_code = 'CACHED_ELEVATED_EVIDENCE'
                $Volume.cached_evidence_status = 'valid'
                $Volume.evidence_source = 'cached-elevated'
                $Volume.evidence_generated_at = $Generated.ToUniversalTime().ToString('o')
                $Volume.evidence_age_hours = [math]::Round($AgeHours, 2)
                $Volume.volume_status = [string]$Cached.volume_status
                $Volume.protection_status = [string]$Cached.protection_status
                $Volume.encryption_percentage = [int]$Cached.encryption_percentage
                $Volume.encryption_method = [string]$Cached.encryption_method
            }
        }
        catch {
            $Volume.cached_evidence_status = 'unreadable'
        }
    }
}

$Report = [ordered]@{
    schema_version = '1.0'
    generated_at = [DateTime]::UtcNow.ToString('o')
    platform = 'windows'
    probe_status = 'ok'
    privacy_mode = 'sid-only-no-user-identities'
    protected_paths = $ProtectedPaths
    volume = $Volume
}
$Directory = Split-Path -Parent $OutputPath
New-Item -ItemType Directory -Force -Path $Directory | Out-Null
$Temporary = Join-Path $Directory ('.security-posture-probe.{0}.tmp' -f [guid]::NewGuid().ToString('N'))
$Report | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath $Temporary -Encoding UTF8
Move-Item -LiteralPath $Temporary -Destination $OutputPath -Force


