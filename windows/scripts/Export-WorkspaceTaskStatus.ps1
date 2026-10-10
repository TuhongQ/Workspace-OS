[CmdletBinding()]
param(
    [string]$WorkspacePath = 'D:\Workspace',
    [string]$TaskPrefix = 'WorkspaceOS-'
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

function ConvertTo-IsoTimestamp {
    param([DateTime]$Value)
    if ($Value -eq [DateTime]::MinValue) {
        return $null
    }
    return $Value.ToUniversalTime().ToString('o')
}

function Split-TaskArguments {
    param([string]$Value)
    if ([string]::IsNullOrWhiteSpace($Value)) {
        return @()
    }
    return @([regex]::Matches($Value, '"[^"]*"|\S+') | ForEach-Object {
        $Token = $_.Value
        if ($Token.Length -ge 2 -and $Token[0] -eq '"' -and $Token[$Token.Length - 1] -eq '"') {
            $Token.Substring(1, $Token.Length - 2)
        }
        else {
            $Token
        }
    })
}

function Convert-TaskTrigger {
    param($Trigger)
    $ClassName = [string]$Trigger.CimClass.CimClassName
    $Type = if ($ClassName -eq 'MSFT_TaskDailyTrigger') {
        'daily'
    }
    elseif ($ClassName -eq 'MSFT_TaskWeeklyTrigger') {
        'weekly'
    }
    else {
        'unknown'
    }
    $Boundary = [DateTimeOffset]::Parse([string]$Trigger.StartBoundary)
    $Interval = if ($Type -eq 'daily') {
        [int]$Trigger.DaysInterval
    }
    elseif ($Type -eq 'weekly') {
        [int]$Trigger.WeeksInterval
    }
    else {
        $null
    }
    return [ordered]@{
        type = $Type
        time = $Boundary.ToString('HH:mm')
        interval = $Interval
        days_of_week = if ($Type -eq 'weekly') { [int]$Trigger.DaysOfWeek } else { $null }
        start_boundary = $Boundary.ToUniversalTime().ToString('o')
    }
}

$Tasks = @(Get-ScheduledTask | Where-Object TaskName -Like "$TaskPrefix*" | Sort-Object TaskName)
$Records = foreach ($Task in $Tasks) {
    $Info = $Task | Get-ScheduledTaskInfo
    $Actions = @($Task.Actions)
    $Tokens = if ($Actions.Count -eq 1) {
        @(Split-TaskArguments -Value ([string]$Actions[0].Arguments))
    }
    else {
        @()
    }
    $FileIndex = [Array]::IndexOf($Tokens, '-File')
    $Script = if ($FileIndex -ge 0 -and $FileIndex + 1 -lt $Tokens.Count) {
        [string]$Tokens[$FileIndex + 1]
    }
    else {
        $null
    }
    $ArgumentTokens = if ($FileIndex -ge 0 -and $FileIndex + 2 -lt $Tokens.Count) {
        @($Tokens[($FileIndex + 2)..($Tokens.Count - 1)])
    }
    else {
        @()
    }
    $HostTokens = if ($FileIndex -gt 0) {
        @($Tokens[0..($FileIndex - 1)])
    }
    else {
        @()
    }
    $ScriptHash = if (
        -not [string]::IsNullOrWhiteSpace($Script) -and
        (Test-Path -LiteralPath $Script -PathType Leaf)
    ) {
        (Get-FileHash -Algorithm SHA256 -LiteralPath $Script).Hash.ToLowerInvariant()
    }
    else {
        $null
    }
    [ordered]@{
        name = $Task.TaskName
        state = [string]$Task.State
        enabled = ([string]$Task.State -ne 'Disabled')
        last_run_time = ConvertTo-IsoTimestamp -Value ([DateTime]$Info.LastRunTime)
        last_result = [int64]$Info.LastTaskResult
        next_run_time = ConvertTo-IsoTimestamp -Value ([DateTime]$Info.NextRunTime)
        execute = if ($Actions.Count -eq 1) { [string]$Actions[0].Execute } else { $null }
        arguments = if ($Actions.Count -eq 1) { [string]$Actions[0].Arguments } else { $null }
        action_count = $Actions.Count
        script = $Script
        script_sha256 = $ScriptHash
        host_tokens = $HostTokens
        argument_tokens = $ArgumentTokens
        principal = [ordered]@{
            user = [string]$Task.Principal.UserId
            logon_type = [string]$Task.Principal.LogonType
            run_level = [string]$Task.Principal.RunLevel
        }
        trigger_count = @($Task.Triggers).Count
        triggers = @($Task.Triggers | ForEach-Object { Convert-TaskTrigger -Trigger $_ })
        settings = [ordered]@{
            execution_time_limit = [string]$Task.Settings.ExecutionTimeLimit
            start_when_available = [bool]$Task.Settings.StartWhenAvailable
            allow_start_on_batteries = -not [bool]$Task.Settings.DisallowStartIfOnBatteries
            stop_on_battery = [bool]$Task.Settings.StopIfGoingOnBatteries
        }
    }
}

$Report = [ordered]@{
    schema_version = '1.1'
    generated_at = [DateTime]::UtcNow.ToString('o')
    task_prefix = $TaskPrefix
    task_count = $Records.Count
    healthy = (@($Records | Where-Object {
        -not $_.enabled -or $_.last_result -notin @(0, 267009, 267011)
    }).Count -eq 0)
    tasks = @($Records)
}

$Output = Join-Path $WorkspacePath '08_Indexes\Health\scheduled-tasks.json'
New-Item -ItemType Directory -Force -Path (Split-Path -Parent $Output) | Out-Null
$Report | ConvertTo-Json -Depth 6 | Set-Content -Encoding UTF8 -LiteralPath $Output
$Report
