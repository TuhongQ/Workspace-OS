[CmdletBinding()]
param(
    [string]$WorkspacePath,
    [string]$NasPath,
    [switch]$NoOpen
)

$ErrorActionPreference = 'Stop'
Add-Type -AssemblyName PresentationFramework

$Root = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
$Cli = Join-Path $Root 'scripts\python\workspace_cli.py'
$Server = Join-Path $Root 'scripts\python\dashboard_sync_server.py'
$BundledPython = Join-Path $Root 'runtime\python\python.exe'
$PythonExecutable = if (Test-Path -LiteralPath $BundledPython) { $BundledPython } else { 'python' }
$SettingsDirectory = Join-Path $env:APPDATA 'WorkspaceOS'
$SettingsPath = Join-Path $SettingsDirectory 'control-center-settings.json'
$DashboardDirectory = Join-Path $env:LOCALAPPDATA 'WorkspaceOS\Dashboard'
$Dashboard = Join-Path $DashboardDirectory 'file-locations.html'
$LogDirectory = Join-Path $env:LOCALAPPDATA 'WorkspaceOS\Logs'
$LogPath = Join-Path $LogDirectory 'nexus-launch.log'

New-Item -ItemType Directory -Path $DashboardDirectory, $LogDirectory -Force | Out-Null

function Write-LauncherLog([string]$Message) {
    Add-Content -LiteralPath $LogPath -Encoding utf8 -Value "[$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')] $Message"
}

function Quote-Arg([string]$Value) {
    if ($null -eq $Value) { $Value = '' }
    $builder = New-Object System.Text.StringBuilder
    [void]$builder.Append('"')
    $slashes = 0
    foreach ($character in $Value.ToCharArray()) {
        if ($character -eq '\') { $slashes += 1; continue }
        if ($character -eq '"') {
            if ($slashes -gt 0) { [void]$builder.Append(('\' * ($slashes * 2 + 1))) } else { [void]$builder.Append('\') }
            [void]$builder.Append('"')
            $slashes = 0
            continue
        }
        if ($slashes -gt 0) { [void]$builder.Append(('\' * $slashes)); $slashes = 0 }
        [void]$builder.Append($character)
    }
    if ($slashes -gt 0) { [void]$builder.Append(('\' * ($slashes * 2))) }
    [void]$builder.Append('"')
    return $builder.ToString()
}

function Invoke-WorkspaceCli([string[]]$Arguments) {
    $info = New-Object System.Diagnostics.ProcessStartInfo
    $info.FileName = $PythonExecutable
    $info.Arguments = (Quote-Arg $Cli) + ' ' + (($Arguments | ForEach-Object { Quote-Arg ([string]$_) }) -join ' ')
    $info.WorkingDirectory = $Root
    $info.UseShellExecute = $false
    $info.CreateNoWindow = $true
    $info.RedirectStandardOutput = $true
    $info.RedirectStandardError = $true
    $process = New-Object System.Diagnostics.Process
    $process.StartInfo = $info
    [void]$process.Start()
    $stdout = $process.StandardOutput.ReadToEnd()
    $stderr = $process.StandardError.ReadToEnd()
    $process.WaitForExit()
    return [pscustomobject]@{ ExitCode = $process.ExitCode; Output = $stdout; Error = $stderr }
}

function Normalize-WorkspacePath([string]$Value) {
    try { return ([IO.Path]::GetFullPath($Value)).TrimEnd('\', '/').ToLowerInvariant() }
    catch { return ([string]$Value).TrimEnd('\', '/').ToLowerInvariant() }
}

function Find-ExistingDashboardUrl([string]$ExpectedWorkspace, [string]$ExpectedNas) {
    try {
        $processes = @(Get-CimInstance Win32_Process -ErrorAction Stop |
            Where-Object { $_.Name -like 'python*' -and $_.CommandLine -like '*dashboard_sync_server.py*' })
        foreach ($process in $processes) {
            if ($process.CommandLine -notmatch '--port\s+"?(\d+)') { continue }
            $candidatePort = [int]$Matches[1]
            $health = "http://127.0.0.1:$candidatePort/api/health"
            try {
                $status = Invoke-RestMethod -Uri $health -TimeoutSec 1
                $workspaceMatches = (Normalize-WorkspacePath ([string]$status.computer)) -eq (Normalize-WorkspacePath $ExpectedWorkspace)
                $nasMatches = (Normalize-WorkspacePath ([string]$status.nas)) -eq (Normalize-WorkspacePath $ExpectedNas)
                if ($status.ok -and $status.api_version -and $workspaceMatches -and $nasMatches) {
                    return "http://127.0.0.1:$candidatePort/dashboard#compare"
                }
            } catch { }
        }
    } catch { }
    return $null
}

try {
    if (-not (Test-Path -LiteralPath $Cli -PathType Leaf)) { throw "Workspace OS core was not found: $Cli" }
    if (-not (Test-Path -LiteralPath $Server -PathType Leaf)) { throw "NEXUS service was not found: $Server" }

    $settings = $null
    if (Test-Path -LiteralPath $SettingsPath -PathType Leaf) {
        try { $settings = Get-Content -LiteralPath $SettingsPath -Raw -Encoding utf8 | ConvertFrom-Json } catch { }
    }

    if ([string]::IsNullOrWhiteSpace($WorkspacePath)) {
        if ($settings -and $settings.workspace_path) { $WorkspacePath = [string]$settings.workspace_path }
        elseif (Test-Path -LiteralPath 'D:\Workspace' -PathType Container) { $WorkspacePath = 'D:\Workspace' }
        else { $WorkspacePath = Join-Path $env:USERPROFILE 'Workspace' }
    }
    $WorkspacePath = [IO.Path]::GetFullPath($WorkspacePath)
    if (-not (Test-Path -LiteralPath $WorkspacePath -PathType Container)) {
        New-Item -ItemType Directory -Path $WorkspacePath -Force | Out-Null
    }

    if ([string]::IsNullOrWhiteSpace($NasPath)) {
        if ($settings -and $settings.nas_path) { $NasPath = [string]$settings.nas_path }
        else { $NasPath = 'W:\' }
    }
    if (-not (Test-Path -LiteralPath $NasPath -PathType Container)) {
        $fallbacks = @()
        try {
            $fallbacks += @(Get-SmbMapping -ErrorAction Stop |
                Where-Object { $_.Status -eq 'OK' -and $_.RemotePath -like '*\Workspace' } |
                Select-Object -ExpandProperty RemotePath)
        } catch { }
        $fallbacks += '\\192.168.1.9\Workspace'
        $fallbacks += '\\192.168.100.110\Workspace'
        foreach ($candidate in @($fallbacks | Select-Object -Unique)) {
            if (Test-Path -LiteralPath $candidate -PathType Container) { $NasPath = $candidate; break }
        }
    }

    $alertsPath = Join-Path $WorkspacePath '08_Indexes\Alerts\control-plane.json'
    $alerts = Invoke-WorkspaceCli @('alerts', '--workspace', $WorkspacePath, '--output', $alertsPath)
    if ($alerts.ExitCode -ne 0) {
        Write-LauncherLog "Live alert refresh was skipped: $($alerts.Error.Trim())"
    }

    $existingUrl = Find-ExistingDashboardUrl -ExpectedWorkspace $WorkspacePath -ExpectedNas $NasPath
    if ($existingUrl) {
        try {
            $refreshUrl = $existingUrl.Replace('/dashboard#compare', '/api/refresh')
            Invoke-RestMethod -Method Post -Uri $refreshUrl -TimeoutSec 120 | Out-Null
        } catch {
            Write-LauncherLog "Running NEXUS refresh was skipped: $($_.Exception.Message)"
        }
        Write-LauncherLog "Reusing the running NEXUS service: $existingUrl"
        if (-not $NoOpen) { Start-Process $existingUrl }
        Write-Output $existingUrl
        exit 0
    }

    Write-LauncherLog "Rendering NEXUS: Workspace=$WorkspacePath; NAS=$NasPath"
    $render = Invoke-WorkspaceCli @(
        'locations', '--computer', $WorkspacePath, '--nas', $NasPath,
        '--output', $Dashboard, '--refresh-nas-capacity'
    )
    if ($render.ExitCode -ne 0 -or -not (Test-Path -LiteralPath $Dashboard -PathType Leaf)) {
        Write-LauncherLog "Capacity refresh failed; retrying with cached NAS metadata: $($render.Error.Trim())"
        $render = Invoke-WorkspaceCli @('locations', '--computer', $WorkspacePath, '--nas', $NasPath, '--output', $Dashboard)
    }
    if ($render.ExitCode -ne 0 -or -not (Test-Path -LiteralPath $Dashboard -PathType Leaf)) {
        throw "NEXUS rendering failed: $($render.Error.Trim())"
    }

    $listener = [System.Net.Sockets.TcpListener]::new([System.Net.IPAddress]::Loopback, 0)
    $listener.Start()
    $port = ([System.Net.IPEndPoint]$listener.LocalEndpoint).Port
    $listener.Stop()

    $serverInfo = New-Object System.Diagnostics.ProcessStartInfo
    $serverInfo.FileName = $PythonExecutable
    $serverInfo.Arguments = (Quote-Arg $Server) +
        ' --computer ' + (Quote-Arg $WorkspacePath) +
        ' --nas ' + (Quote-Arg $NasPath) +
        ' --dashboard ' + (Quote-Arg $Dashboard) +
        ' --port ' + $port
    $serverInfo.WorkingDirectory = $Root
    $serverInfo.UseShellExecute = $false
    $serverInfo.CreateNoWindow = $true
    $serverProcess = New-Object System.Diagnostics.Process
    $serverProcess.StartInfo = $serverInfo
    [void]$serverProcess.Start()

    $url = "http://127.0.0.1:$port/dashboard#compare"
    $healthUrl = "http://127.0.0.1:$port/api/health"
    $ready = $false
    for ($attempt = 0; $attempt -lt 30; $attempt++) {
        Start-Sleep -Milliseconds 150
        try {
            if ((Invoke-WebRequest -UseBasicParsing -Uri $healthUrl -TimeoutSec 1).StatusCode -eq 200) {
                $ready = $true
                break
            }
        } catch { }
    }
    if (-not $ready) { throw 'NEXUS local service startup timed out' }

    Write-LauncherLog "NEXUS started: $url"
    if (-not $NoOpen) { Start-Process $url }
    Write-Output $url
    exit 0
} catch {
    Write-LauncherLog "Startup failed: $($_.Exception.Message)"
    if (-not $NoOpen) {
        [System.Windows.MessageBox]::Show(
            "Workspace OS 2.0 NEXUS could not start.`n`n$($_.Exception.Message)`n`nLog: $LogPath",
            'Workspace OS 2.0', 'OK', 'Error'
        ) | Out-Null
    }
    Write-Error $_
    exit 2
}
