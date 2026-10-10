[CmdletBinding(SupportsShouldProcess)]
param(
    [string]$WorkspacePath = 'D:\Workspace',
    [string]$SnapshotPath = 'D:\WorkspaceSnapshots',
    [string]$NasPath = 'W:\',
    [switch]$Replace
)
Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

function Quote-TaskArgument {
    param([string]$Value)
    if ($null -eq $Value -or $Value.Length -eq 0) {
        return '""'
    }
    if ($Value -notmatch '[\s"]') {
        return $Value
    }
    # Windows native command-line quoting: escape quotes and double trailing
    # backslashes before the closing quote.
    $Escaped = [regex]::Replace($Value, '(\\*)"', '$1$1\"')
    $Escaped = [regex]::Replace($Escaped, '(\\+)$', '$1$1')
    return '"' + $Escaped + '"'
}

$PowerShell = (Get-Command powershell.exe -ErrorAction Stop).Source
$ScriptRoot = $PSScriptRoot
$Definitions = @(
    @{
        Name = 'WorkspaceOS-DailySnapshot'
        Script = Join-Path $ScriptRoot 'New-WorkspaceSnapshot.ps1'
        Arguments = @('-WorkspacePath', $WorkspacePath, '-Destination', $SnapshotPath, '-ExcludeRebuildableCache')
        Trigger = New-ScheduledTaskTrigger -Daily -At '01:30'
        Description = 'Workspace OS verified daily snapshot with rebuildable caches excluded.'
    },
    @{
        Name = 'WorkspaceOS-DailyRetention'
        Script = Join-Path $ScriptRoot 'Invoke-WorkspaceRetention.ps1'
        Arguments = @('-Destination', $SnapshotPath)
        Trigger = New-ScheduledTaskTrigger -Daily -At '03:30'
        Description = 'Workspace OS GFS retention. Expired snapshots move to recoverable trash.'
    },
    @{
        Name = 'WorkspaceOS-DailyDoctor'
        Script = Join-Path $ScriptRoot 'Invoke-WorkspaceDoctor.ps1'
        Arguments = @('-WorkspacePath', $WorkspacePath, '-SnapshotPath', $SnapshotPath, '-NasPath', $NasPath)
        Trigger = New-ScheduledTaskTrigger -Daily -At '06:00'
        Description = 'Workspace OS daily health report for workspace, snapshots, storage, and NAS.'
    },
    @{
        Name = 'WorkspaceOS-WeeklySnapshotVerify'
        Script = Join-Path $ScriptRoot 'Test-LatestWorkspaceSnapshot.ps1'
        Arguments = @('-WorkspacePath', $WorkspacePath, '-SnapshotPath', $SnapshotPath)
        Trigger = New-ScheduledTaskTrigger -Weekly -DaysOfWeek Sunday -At '04:30'
        Description = 'Workspace OS weekly full SHA-256 verification of the newest snapshot.'
    },
    @{
        Name = 'WorkspaceOS-WeeklyRestoreDrill'
        Script = Join-Path $ScriptRoot 'Test-WorkspaceRestoreDrill.ps1'
        Arguments = @(
            '-WorkspacePath', $WorkspacePath,
            '-SnapshotPath', $SnapshotPath,
            '-RestoreRoot', 'D:\WorkspaceRestoreTests\Automated'
        )
        Trigger = New-ScheduledTaskTrigger -Weekly -DaysOfWeek Sunday -At '05:00'
        Description = 'Workspace OS isolated canary restore with SHA-256 read-back and observed RTO.'
        AllowOnBattery = $true
    },
    @{
        Name = 'WorkspaceOS-WeeklyAudit'
        Script = Join-Path $ScriptRoot 'Audit-Workspace.ps1'
        Arguments = @('-WorkspacePath', $WorkspacePath)
        Trigger = New-ScheduledTaskTrigger -Weekly -DaysOfWeek Sunday -At '05:30'
        Description = 'Workspace OS weekly structure, naming, release, and duplicate audit.'
    },
    @{
        Name = 'WorkspaceOS-WeeklyRecoveryKit'
        Script = Join-Path $ScriptRoot 'New-WorkspaceRecoveryKit.ps1'
        Arguments = @(
            '-RepositoryPath', (Resolve-Path (Join-Path $ScriptRoot '..\..')).Path,
            '-WorkspacePath', $WorkspacePath
        )
        Trigger = New-ScheduledTaskTrigger -Weekly -DaysOfWeek Sunday -At '07:30'
        Description = 'Workspace OS weekly portable, self-verifying recovery kit.'
    },
    @{
        Name = 'WorkspaceOS-WeeklyRecoveryKitRetention'
        Script = Join-Path $ScriptRoot 'Invoke-WorkspaceRecoveryKitRetention.ps1'
        Arguments = @('-WorkspacePath', $WorkspacePath)
        Trigger = New-ScheduledTaskTrigger -Weekly -DaysOfWeek Sunday -At '07:45'
        Description = 'Workspace OS recovery-kit retention. Expired verified pairs move to recoverable trash.'
    },
    @{
        Name = 'WorkspaceOS-DailyControlPlane'
        Script = Join-Path $ScriptRoot 'Update-WorkspaceControlPlane.ps1'
        Arguments = @('-WorkspacePath', $WorkspacePath, '-SnapshotPath', $SnapshotPath, '-NasPath', $NasPath)
        Trigger = New-ScheduledTaskTrigger -Daily -At '06:30'
        Description = 'Workspace OS daily search, graph, health, and alert control-plane refresh.'
    }
)

$Existing = @($Definitions | Where-Object { Get-ScheduledTask -TaskName $_.Name -ErrorAction SilentlyContinue })
if ($Existing.Count -and -not $Replace) {
    $Names = ($Existing.Name -join ', ')
    throw "Tasks already exist: $Names. Use -Replace to update them."
}

$Principal = New-ScheduledTaskPrincipal -UserId ([System.Security.Principal.WindowsIdentity]::GetCurrent().Name) -LogonType Interactive -RunLevel Limited
foreach ($Definition in $Definitions) {
    $ArgumentParts = @(
        '-NoProfile',
        '-ExecutionPolicy', 'Bypass',
        '-File', (Quote-TaskArgument $Definition.Script)
    )
    foreach ($Item in $Definition.Arguments) {
        $ArgumentParts += Quote-TaskArgument "$Item"
    }
    $ArgumentText = $ArgumentParts -join ' '
    $SettingsParameters = @{
        StartWhenAvailable = $true
        ExecutionTimeLimit = (New-TimeSpan -Hours 6)
    }
    if ($Definition.ContainsKey('AllowOnBattery') -and $Definition.AllowOnBattery) {
        $SettingsParameters.AllowStartIfOnBatteries = $true
        $SettingsParameters.DontStopIfGoingOnBatteries = $true
    }
    $Settings = New-ScheduledTaskSettingsSet @SettingsParameters
    $Action = New-ScheduledTaskAction -Execute $PowerShell -Argument $ArgumentText
    $Task = New-ScheduledTask -Action $Action -Trigger $Definition.Trigger -Settings $Settings -Principal $Principal -Description $Definition.Description
    if ($PSCmdlet.ShouldProcess($Definition.Name, 'Register Workspace OS maintenance task')) {
        $Parameters = @{ TaskName = $Definition.Name; InputObject = $Task }
        if ($Replace) { $Parameters.Force = $true }
        Register-ScheduledTask @Parameters | Out-Null
    }
}
