[CmdletBinding(SupportsShouldProcess = $true, ConfirmImpact = 'Medium')]
param(
    [string]$WorkspacePath = 'D:\Workspace',
    [switch]$Apply,
    [string]$BackupRoot,
    [string]$OutputPath
)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

if ($env:OS -ne 'Windows_NT') {
    throw '受保护目录 ACL 加固仅支持 Windows。'
}

$WorkspaceRoot = [IO.Path]::GetFullPath($WorkspacePath).TrimEnd(
    [IO.Path]::DirectorySeparatorChar
)
$Marker = Join-Path $WorkspaceRoot '.workspace-os.json'
if (-not (Test-Path -LiteralPath $Marker -PathType Leaf)) {
    throw "目标不是已初始化的 Workspace OS 根目录：$WorkspaceRoot"
}

$Output = if ([string]::IsNullOrWhiteSpace($OutputPath)) {
    Join-Path $WorkspaceRoot '08_Indexes\Security\acl-hardening.json'
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
    throw "ACL 加固报告必须位于 08_Indexes\Security：$Output"
}
$CurrentUserSid = [Security.Principal.WindowsIdentity]::GetCurrent().User.Value
$TrustedSids = @(
    $CurrentUserSid,
    'S-1-5-18',
    'S-1-5-32-544'
)
$BroadSids = @(
    'S-1-1-0',
    'S-1-5-11',
    'S-1-5-32-545'
)
$RelativePaths = @(
    '07_Admin\Accounts',
    '07_Admin\Certificates',
    '07_Admin\Private'
)

function Convert-IdentityToSid {
    param([Parameter(Mandatory)]$Identity)
    try {
        return $Identity.Translate(
            [Security.Principal.SecurityIdentifier]
        ).Value
    }
    catch {
        return $null
    }
}

function Test-RootAclDesired {
    param([Parameter(Mandatory)][string]$Path)
    $Acl = Get-Acl -LiteralPath $Path -ErrorAction Stop
    if (-not $Acl.AreAccessRulesProtected) {
        return $false
    }
    $Seen = @{}
    foreach ($Rule in $Acl.Access) {
        $Sid = Convert-IdentityToSid -Identity $Rule.IdentityReference
        if (
            -not $Sid -or
            $Rule.AccessControlType -ne
                [Security.AccessControl.AccessControlType]::Allow -or
            $Rule.IsInherited -or
            $Sid -notin $TrustedSids
        ) {
            return $false
        }
        $FullControl = [int64][Security.AccessControl.FileSystemRights]::FullControl
        $Rights = [int64]$Rule.FileSystemRights
        $RequiredInheritance = (
            [Security.AccessControl.InheritanceFlags]::ContainerInherit -bor
            [Security.AccessControl.InheritanceFlags]::ObjectInherit
        )
        if (
            ($Rights -band $FullControl) -ne $FullControl -or
            ($Rule.InheritanceFlags -band $RequiredInheritance) -ne
                $RequiredInheritance -or
            $Rule.PropagationFlags -ne
                [Security.AccessControl.PropagationFlags]::None
        ) {
            return $false
        }
        $Seen[$Sid] = $true
    }
    return @($TrustedSids | Where-Object { -not $Seen.ContainsKey($_) }).Count -eq 0
}

function Test-DescendantsInherit {
    param([Parameter(Mandatory)][string]$Path)
    foreach ($Item in Get-ChildItem -Force -Recurse -LiteralPath $Path) {
        $Acl = Get-Acl -LiteralPath $Item.FullName -ErrorAction Stop
        if ($Acl.AreAccessRulesProtected) {
            return $false
        }
        foreach ($Rule in $Acl.Access) {
            if (-not $Rule.IsInherited) {
                return $false
            }
            $Sid = Convert-IdentityToSid -Identity $Rule.IdentityReference
            if (-not $Sid -or $Sid -notin $TrustedSids) {
                return $false
            }
        }
    }
    return $true
}

function Test-DesiredState {
    param([Parameter(Mandatory)][string]$Path)
    return (
        (Test-RootAclDesired -Path $Path) -and
        (Test-DescendantsInherit -Path $Path)
    )
}

function Write-AtomicText {
    param(
        [Parameter(Mandatory)][string]$Path,
        [Parameter(Mandatory)][string]$Content
    )
    $Directory = Split-Path -Parent $Path
    New-Item -ItemType Directory -Force -Path $Directory | Out-Null
    $Temporary = Join-Path $Directory (
        '.{0}.{1}.tmp' -f
        ([IO.Path]::GetFileName($Path)),
        [guid]::NewGuid().ToString('N')
    )
    try {
        [IO.File]::WriteAllText(
            $Temporary,
            $Content,
            [Text.UTF8Encoding]::new($false)
        )
        Move-Item -LiteralPath $Temporary -Destination $Path -Force
    }
    finally {
        Remove-Item -LiteralPath $Temporary -Force -ErrorAction SilentlyContinue
    }
}

function Write-Report {
    param([Parameter(Mandatory)]$Report)
    $Json = $Report | ConvertTo-Json -Depth 8
    Write-AtomicText -Path $Output -Content ($Json + [Environment]::NewLine)
}

$Targets = @()
foreach ($Relative in $RelativePaths) {
    $Target = [IO.Path]::GetFullPath((Join-Path $WorkspaceRoot $Relative))
    if (-not $Target.StartsWith($WorkspaceRoot + '\', [StringComparison]::OrdinalIgnoreCase)) {
        throw "受保护目录越出 Workspace：$Relative"
    }
    $Exists = Test-Path -LiteralPath $Target -PathType Container
    $Desired = $Exists -and (Test-DesiredState -Path $Target)
    $Targets += [ordered]@{
        relative = ($Relative -replace '\\', '/')
        path = $Target
        exists = $Exists
        desired_before = $Desired
        action = if (-not $Exists) {
            'missing'
        }
        elseif ($Desired) {
            'unchanged'
        }
        else {
            'would-protect'
        }
        desired_after = $Desired
    }
}

$NeedsChange = @($Targets | Where-Object {
    $_.exists -and -not $_.desired_before
})
$EffectiveApply = $Apply -and -not $WhatIfPreference
$Report = [ordered]@{
    schema_version = '1.0'
    generated_at = [DateTime]::UtcNow.ToString('o')
    workspace = $WorkspaceRoot
    status = if ($NeedsChange.Count -eq 0) {
        'unchanged'
    }
    elseif ($EffectiveApply) {
        'applying'
    }
    else {
        'preview'
    }
    privacy_mode = 'sid-classes-no-user-names'
    policy = [ordered]@{
        inheritance_protected = $true
        trusted_principal_classes = @(
            'current-workspace-user',
            'system',
            'local-administrators'
        )
        broad_principal_sids_denied = $BroadSids
    }
    backup_root = $null
    targets = $Targets
    summary = [ordered]@{
        configured = $Targets.Count
        existing = @($Targets | Where-Object { $_.exists }).Count
        missing = @($Targets | Where-Object { -not $_.exists }).Count
        changes_required = $NeedsChange.Count
        changed = 0
        verified = @($Targets | Where-Object { $_.desired_before }).Count
        failed = 0
        content_overwrites = 0
        content_deletions = 0
    }
    outputs = @($Output)
}

if (-not $EffectiveApply -or $NeedsChange.Count -eq 0) {
    Write-Report -Report $Report
    $Report | ConvertTo-Json -Depth 8
    return
}

$Backup = if ([string]::IsNullOrWhiteSpace($BackupRoot)) {
    Join-Path $WorkspaceRoot (
        '07_Admin\WorkspaceOS\logs\acl-backups\{0}' -f
        (Get-Date -Format 'yyyyMMdd-HHmmss')
    )
}
else {
    [IO.Path]::GetFullPath($BackupRoot)
}
if (Test-Path -LiteralPath $Backup) {
    throw "ACL 备份目录已存在，拒绝覆盖：$Backup"
}
foreach ($Item in $Targets) {
    if (
        $Backup.Equals($Item.path, [StringComparison]::OrdinalIgnoreCase) -or
        $Backup.StartsWith(
            $Item.path + [IO.Path]::DirectorySeparatorChar,
            [StringComparison]::OrdinalIgnoreCase
        )
    ) {
        throw "ACL 备份目录不能位于受保护目录内：$Backup"
    }
}

try {
    New-Item -ItemType Directory -Path $Backup | Out-Null
    $Report.backup_root = $Backup
    $AdminRoot = Join-Path $WorkspaceRoot '07_Admin'
    Push-Location $AdminRoot
    try {
        foreach ($Item in $NeedsChange) {
            $Leaf = Split-Path -Leaf $Item.path
            $AclBackup = Join-Path $Backup ($Leaf + '.acl')
            & icacls.exe $Leaf /save $AclBackup /t /c | Out-Null
            if ($LASTEXITCODE -ne 0 -or -not (Test-Path -LiteralPath $AclBackup -PathType Leaf)) {
                throw "ACL 备份失败：$($Item.relative)"
            }
        }
    }
    finally {
        Pop-Location
    }

    $RestoreLines = @(
        '# Workspace OS 受保护目录 ACL 回滚',
        '',
        '只有在确认需要撤销权限收紧时，才在管理员 PowerShell 中运行：',
        '',
        '```powershell',
        ('Set-Location "{0}"' -f $Backup)
    )
    foreach ($Item in $NeedsChange) {
        $Leaf = Split-Path -Leaf $Item.path
        $RestoreLines += (
            'icacls.exe "{0}" /restore ".\{1}.acl" /c' -f
            $AdminRoot,
            $Leaf
        )
    }
    $RestoreLines += @(
        '```',
        '',
        '回滚后必须重新运行 `Audit-WorkspaceSecurityPosture.ps1`。'
    )
    Write-AtomicText `
        -Path (Join-Path $Backup 'RESTORE.md') `
        -Content (($RestoreLines -join [Environment]::NewLine) + [Environment]::NewLine)

    foreach ($Item in $NeedsChange) {
        if (-not $PSCmdlet.ShouldProcess($Item.path, '备份后应用最小权限 ACL')) {
            continue
        }
        & icacls.exe $Item.path /inheritance:r | Out-Null
        if ($LASTEXITCODE -ne 0) {
            throw "阻断继承失败：$($Item.relative)"
        }
        & icacls.exe $Item.path /grant:r `
            ("*{0}:(OI)(CI)F" -f $CurrentUserSid) `
            '*S-1-5-18:(OI)(CI)F' `
            '*S-1-5-32-544:(OI)(CI)F' | Out-Null
        if ($LASTEXITCODE -ne 0) {
            throw "授予最小权限失败：$($Item.relative)"
        }
        foreach ($Child in Get-ChildItem -Force -LiteralPath $Item.path) {
            & icacls.exe $Child.FullName /reset /t /c | Out-Null
            if ($LASTEXITCODE -ne 0) {
                throw "重置子项继承失败：$($Item.relative)"
            }
        }
        $Verified = Test-DesiredState -Path $Item.path
        $Item.action = if ($Verified) { 'protected' } else { 'verification-failed' }
        $Item.desired_after = $Verified
        if (-not $Verified) {
            throw "应用后 ACL 自检失败：$($Item.relative)"
        }
        $Report.summary.changed += 1
        $Report.summary.verified += 1
    }
    $Report.status = 'applied'
}
catch {
    $Report.status = 'failed'
    $Report.summary.failed = 1
    $Report.failure = [ordered]@{
        code = 'ACL_HARDENING_FAILED'
        message = $_.Exception.Message
    }
    Write-Report -Report $Report
    throw
}

Write-Report -Report $Report
$Report | ConvertTo-Json -Depth 8




