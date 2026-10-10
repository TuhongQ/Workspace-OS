[CmdletBinding()]
param(
    [string]$WorkspacePath = 'D:\Workspace',
    [string]$SnapshotPath = 'D:\WorkspaceSnapshots',
    [string]$NasPath = 'W:\',
    [int]$PublishRetryHours = 6,
    [ValidateRange(10, 300)]
    [int]$PublishTimeoutSeconds = 60
)
. (Join-Path $PSScriptRoot 'WorkspaceOS.Common.ps1')
$Database = Join-Path $WorkspacePath '08_Indexes\Search\workspace-search.db'
$SearchStatus = Join-Path $WorkspacePath '08_Indexes\Search\search-status.json'
$Graph = Join-Path $WorkspacePath '08_Indexes\Graph\workspace-graph.json'
$DeviceManifest = Join-Path $WorkspacePath '08_Indexes\Devices\local-device-manifest.json'
$Health = Join-Path $WorkspacePath '08_Indexes\Health\workspace-health.json'
$NasProbe = Join-Path $WorkspacePath '08_Indexes\Health\nas-probe.json'
$Alerts = Join-Path $WorkspacePath '08_Indexes\Alerts\control-plane.json'
$Recovery = Join-Path $WorkspacePath '08_Indexes\Recovery\recovery-readiness.json'
$Security = Join-Path $WorkspacePath '08_Indexes\Security\change-guard.json'
$SecurityAudit = Join-Path $WorkspacePath '08_Indexes\Security\security-audit.json'
$SecurityBaseline = Join-Path $WorkspacePath '08_Indexes\Security\change-baseline.json'
$NotificationOutbox = Join-Path $WorkspacePath '08_Indexes\Alerts\notification-outbox.json'
$PublishStatus = Join-Path $WorkspacePath '08_Indexes\Alerts\nas-publish-status.json'
$Dashboard = Join-Path $WorkspacePath '08_Indexes\file-locations.html'
$Publisher = Join-Path $PSScriptRoot 'Publish-WorkspaceDashboard.ps1'
$NasProbeWorker = Join-Path $PSScriptRoot 'Probe-WorkspaceNas.ps1'
$TaskStatusExporter = Join-Path $PSScriptRoot 'Export-WorkspaceTaskStatus.ps1'
$TaskStatus = Join-Path $WorkspacePath '08_Indexes\Health\scheduled-tasks.json'
$MaintenanceAudit = Join-Path $WorkspacePath '08_Indexes\Health\maintenance-audit.json'
$MaintenancePolicy = Join-Path (Resolve-Path (Join-Path $PSScriptRoot '..\..')).Path 'config\maintenance-policy.json'
$CurrentTaskUser = [System.Security.Principal.WindowsIdentity]::GetCurrent().Name
$AlertDispatcher = Join-Path $PSScriptRoot 'Dispatch-WorkspaceAlerts.ps1'
$EvidenceStatus = Join-Path $WorkspacePath '08_Indexes\Evidence\status.json'

function Write-NasPublishStatus {
    param(
        [bool]$Success,
        [string]$Code,
        [string]$Message,
        [int]$ExitCode = 0,
        [int]$DurationMilliseconds = 0
    )
    $Status = [ordered]@{
        schema_version = '1.0'
        generated_at = [DateTime]::UtcNow.ToString('o')
        success = $Success
        code = $Code
        message = $Message
        exit_code = $ExitCode
        duration_ms = $DurationMilliseconds
        timeout_seconds = $PublishTimeoutSeconds
        destination = (Join-Path $NasPath '08_Indexes')
    }
    $StatusDirectory = Split-Path -Parent $PublishStatus
    New-Item -ItemType Directory -Force -Path $StatusDirectory | Out-Null
    $Status | ConvertTo-Json -Depth 4 | Set-Content -Encoding UTF8 -LiteralPath $PublishStatus
}

function Write-NasProbeStatus {
    param(
        [string]$Status,
        [int]$DurationMilliseconds = 0
    )
    $Probe = [ordered]@{
        schema_version = '1.0'
        generated_at = [DateTime]::UtcNow.ToString('o')
        status = $Status
        marker_valid = $false
        duration_ms = $DurationMilliseconds
    }
    $ProbeDirectory = Split-Path -Parent $NasProbe
    New-Item -ItemType Directory -Force -Path $ProbeDirectory | Out-Null
    $Temporary = Join-Path $ProbeDirectory ('.nas-probe.{0}.tmp' -f [guid]::NewGuid().ToString('N'))
    $Probe | ConvertTo-Json -Depth 3 | Set-Content -Encoding UTF8 -LiteralPath $Temporary
    Move-Item -LiteralPath $Temporary -Destination $NasProbe -Force
}

Invoke-WorkspaceOSPython -Arguments @(
    'search-maintain', '--workspace', $WorkspacePath,
    '--database', $Database, '--content', '--output', $SearchStatus
)
Invoke-WorkspaceOSPython -Arguments @('graph-build', '--workspace', $WorkspacePath, '--output', $Graph)
$DeviceId = if ([string]::IsNullOrWhiteSpace($env:COMPUTERNAME)) { 'windows-local' } else { $env:COMPUTERNAME }
Invoke-WorkspaceOSPython -Arguments @(
    'device-manifest', '--workspace', $WorkspacePath,
    '--device-id', $DeviceId, '--output', $DeviceManifest
)
Invoke-WorkspaceOSPython -Arguments @(
    'change-guard', '--workspace', $WorkspacePath,
    '--baseline', $SecurityBaseline, '--output', $Security
)
Invoke-WorkspaceOSPython -Arguments @(
    'security-audit', '--workspace', $WorkspacePath, '--output', $SecurityAudit
)
& (Join-Path $PSScriptRoot 'Audit-WorkspaceSecurityPosture.ps1') `
    -WorkspacePath $WorkspacePath | Out-Null
Invoke-WorkspaceOSPython -Arguments @(
    'evidence-verify', '--workspace', $WorkspacePath, '--output', $EvidenceStatus
)

# Any filesystem operation against an unhealthy SMB mapping can block for
# minutes. Run even the lightweight availability check in a disposable process
# and pass its local result to Python; local maintenance never touches NAS
# synchronously after this point.
$NasProbeTemporary = Join-Path `
    (Split-Path -Parent $NasProbe) `
    ('.nas-probe-worker.{0}.tmp' -f [guid]::NewGuid().ToString('N'))
$NasProbeArgumentValues = @(
    '-NoProfile',
    '-ExecutionPolicy', 'Bypass',
    '-File', $NasProbeWorker,
    '-NasPath', (Join-Path $NasPath '.'),
    '-OutputPath', $NasProbeTemporary
)
$NasProbeArguments = ($NasProbeArgumentValues | ForEach-Object {
    if ($_ -match '\s') { '"{0}"' -f ($_ -replace '"', '\"') } else { $_ }
}) -join ' '
$NasProbeTimer = [Diagnostics.Stopwatch]::StartNew()
try {
    $NasProbeProcess = Start-Process `
        -FilePath (Join-Path $PSHOME 'powershell.exe') `
        -ArgumentList $NasProbeArguments `
        -WindowStyle Hidden `
        -PassThru
    if (-not $NasProbeProcess.WaitForExit(5000)) {
        $NasProbeProcess.Kill()
        $null = $NasProbeProcess.WaitForExit(1000)
        $NasProbeTimer.Stop()
        Write-NasProbeStatus -Status 'timeout' -DurationMilliseconds ([int]$NasProbeTimer.ElapsedMilliseconds)
    }
    elseif ($NasProbeProcess.ExitCode -eq 0 -and (Test-Path -LiteralPath $NasProbeTemporary -PathType Leaf)) {
        $NasProbeTimer.Stop()
        Move-Item -LiteralPath $NasProbeTemporary -Destination $NasProbe -Force
    }
    else {
        $NasProbeTimer.Stop()
        Write-NasProbeStatus -Status 'unavailable' -DurationMilliseconds ([int]$NasProbeTimer.ElapsedMilliseconds)
    }
}
catch {
    $NasProbeTimer.Stop()
    Write-NasProbeStatus -Status 'unavailable' -DurationMilliseconds ([int]$NasProbeTimer.ElapsedMilliseconds)
}
finally {
    Remove-Item -LiteralPath $NasProbeTemporary -Force -ErrorAction SilentlyContinue
}

Invoke-WorkspaceOSPython -Arguments @(
    'doctor', '--workspace', $WorkspacePath, '--snapshots', $SnapshotPath,
    '--nas', $NasPath, '--nas-probe', $NasProbe, '--output', $Health
)
Invoke-WorkspaceOSPython -Arguments @(
    'recovery-readiness', '--workspace', $WorkspacePath, '--snapshots', $SnapshotPath,
    '--restic-executable', (Join-Path $WorkspacePath '07_Admin\WorkspaceOS\tools\restic.exe'),
    '--output', $Recovery
)
& $TaskStatusExporter -WorkspacePath $WorkspacePath | Out-Null
Invoke-WorkspaceOSPython -Arguments @(
    'maintenance-audit',
    '--task-report', $TaskStatus,
    '--policy', $MaintenancePolicy,
    '--repository', (Resolve-Path (Join-Path $PSScriptRoot '..\..')).Path,
    '--workspace', $WorkspacePath,
    '--snapshots', $SnapshotPath,
    '--nas', $NasPath,
    '--expected-user', $CurrentTaskUser,
    '--output', $MaintenanceAudit
)
Invoke-WorkspaceOSPython -Arguments @('alerts', '--workspace', $WorkspacePath, '--output', $Alerts)
Invoke-WorkspaceOSPython -Arguments @(
    'operations-record', '--workspace', $WorkspacePath,
    '--window-days', '30', '--dedupe-minutes', '30'
)
# Include any rolling SLO/error-budget findings in the same notification cycle.
Invoke-WorkspaceOSPython -Arguments @('alerts', '--workspace', $WorkspacePath, '--output', $Alerts)
Invoke-WorkspaceOSPython -Arguments @(
    'locations', '--computer', $WorkspacePath, '--nas', $NasPath, '--output', $Dashboard
)

# Start-Process flattens ArgumentList into one Windows command line. Quote only
# values containing whitespace: quoting a drive root such as W:\ can make the
# trailing backslash escape the closing quote in native argument parsing.
$ShouldPublish = $true
if ($PublishRetryHours -gt 0 -and (Test-Path -LiteralPath $PublishStatus -PathType Leaf)) {
    try {
        $PreviousPublish = Get-Content -Raw -LiteralPath $PublishStatus | ConvertFrom-Json
        $PreviousAt = [DateTimeOffset]::Parse($PreviousPublish.generated_at)
        $RetryAt = $PreviousAt.AddHours($PublishRetryHours)
        if (-not $PreviousPublish.success -and [DateTimeOffset]::UtcNow -lt $RetryAt) {
            $ShouldPublish = $false
        }
    }
    catch {
        $ShouldPublish = $true
    }
}

if ($ShouldPublish) {
    $PublisherArgumentValues = @(
        '-NoProfile',
        '-ExecutionPolicy', 'Bypass',
        '-File', $Publisher,
        '-WorkspacePath', $WorkspacePath,
        # Avoid a trailing backslash as the final native argument. Windows can
        # preserve the synthetic closing quote as part of a drive-root value.
        '-NasPath', (Join-Path $NasPath '.')
    )
    $PublisherArguments = ($PublisherArgumentValues | ForEach-Object {
        if ($_ -match '\s') {
            '"{0}"' -f ($_ -replace '"', '\"')
        }
        else {
            $_
        }
    }) -join ' '

    try {
        $PublishTimer = [Diagnostics.Stopwatch]::StartNew()
        $PublishProcess = Start-Process `
            -FilePath (Join-Path $PSHOME 'powershell.exe') `
            -ArgumentList $PublisherArguments `
            -WindowStyle Hidden `
            -PassThru
        if (-not $PublishProcess.WaitForExit($PublishTimeoutSeconds * 1000)) {
            $PublishProcess.Kill()
            $PublishTimer.Stop()
            Write-NasPublishStatus `
                -Success $false `
                -Code 'NAS_PUBLISH_TIMEOUT' `
                -Message "NAS dashboard publishing exceeded the $PublishTimeoutSeconds-second safety limit." `
                -DurationMilliseconds ([int]$PublishTimer.ElapsedMilliseconds)
        }
        elseif ($PublishProcess.ExitCode -eq 0) {
            $PublishTimer.Stop()
            Write-NasPublishStatus `
                -Success $true `
                -Code 'NAS_PUBLISH_OK' `
                -Message 'Dashboard HTML, gzip JSON payload, and descriptor were published to NAS.' `
                -DurationMilliseconds ([int]$PublishTimer.ElapsedMilliseconds)
        }
        else {
            $PublishTimer.Stop()
            Write-NasPublishStatus `
                -Success $false `
                -Code 'NAS_PUBLISH_FAILED' `
                -Message 'NAS dashboard publisher returned a non-zero exit code.' `
                -ExitCode ([int]$PublishProcess.ExitCode) `
                -DurationMilliseconds ([int]$PublishTimer.ElapsedMilliseconds)
        }
    }
    catch {
        Write-NasPublishStatus `
            -Success $false `
            -Code 'NAS_PUBLISH_START_FAILED' `
            -Message $_.Exception.Message
    }
}

# Refresh alert aggregation after publishing so the current NAS result is visible
# immediately. A NAS failure is a warning and does not fail local maintenance.
Invoke-WorkspaceOSPython -Arguments @('alerts', '--workspace', $WorkspacePath, '--output', $Alerts)
Invoke-WorkspaceOSPython -Arguments @(
    'notifications', '--workspace', $WorkspacePath, '--min-severity', 'ERROR',
    '--output', $NotificationOutbox
)
& $AlertDispatcher -WorkspacePath $WorkspacePath -DesktopToast
Invoke-WorkspaceOSPython -Arguments @(
    'evidence-append', '--workspace', $WorkspacePath,
    '--event-type', 'control-plane', '--subject', 'scheduled-maintenance'
)
Invoke-WorkspaceOSPython -Arguments @(
    'evidence-verify', '--workspace', $WorkspacePath,
    '--verify-current', '--output', $EvidenceStatus
)
# Refresh the local NEXUS payload with the newly verified evidence head. This
# reuses cached NAS metadata and never performs another SMB traversal.
Invoke-WorkspaceOSPython -Arguments @(
    'locations', '--computer', $WorkspacePath, '--nas', $NasPath, '--output', $Dashboard
)
