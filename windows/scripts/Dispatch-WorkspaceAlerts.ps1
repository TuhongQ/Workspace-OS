[CmdletBinding()]
param(
    [string]$WorkspacePath = 'D:\Workspace',
    [switch]$DesktopToast
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
$AlertsRoot = Join-Path $WorkspacePath '08_Indexes\Alerts'
$OutboxPath = Join-Path $AlertsRoot 'notification-outbox.json'
$StatePath = Join-Path $AlertsRoot 'notification-state.json'

if (-not (Test-Path -LiteralPath $OutboxPath -PathType Leaf)) {
    throw "Notification outbox does not exist: $OutboxPath"
}
$Outbox = Get-Content -Raw -Encoding UTF8 -LiteralPath $OutboxPath | ConvertFrom-Json

if ($Outbox.status -eq 'quiet') {
    [ordered]@{
        schema_version = '1.0'
        updated_at = [DateTime]::UtcNow.ToString('o')
        last_delivered_fingerprint = $null
        channels = @()
    } | ConvertTo-Json -Depth 4 | Set-Content -Encoding UTF8 -LiteralPath $StatePath
    return
}
if ($Outbox.status -ne 'pending') {
    return
}

$Delivered = [System.Collections.Generic.List[string]]::new()
$Failures = [System.Collections.Generic.List[string]]::new()
$Messages = @($Outbox.alerts | Select-Object -First 3 | ForEach-Object {
    '{0}/{1}: {2}' -f $_.source, $_.code, $_.message
})

if ($DesktopToast) {
    try {
        Add-Type -AssemblyName System.Windows.Forms
        Add-Type -AssemblyName System.Drawing
        $Notify = [System.Windows.Forms.NotifyIcon]::new()
        try {
            $Notify.Icon = [System.Drawing.SystemIcons]::Warning
            $Notify.Visible = $true
            $Notify.BalloonTipTitle = "Workspace OS：$($Outbox.alert_count) 个需要处理的告警"
            $Notify.BalloonTipText = ($Messages -join [Environment]::NewLine)
            $Notify.ShowBalloonTip(8000)
            Start-Sleep -Seconds 3
            $Delivered.Add('windows-desktop')
        }
        finally {
            $Notify.Dispose()
        }
    }
    catch {
        $Failures.Add("windows-desktop: $($_.Exception.Message)")
    }
}

$WebhookUrl = [Environment]::GetEnvironmentVariable('WORKSPACEOS_ALERT_WEBHOOK_URL', 'User')
if (-not $WebhookUrl) {
    $WebhookUrl = [Environment]::GetEnvironmentVariable('WORKSPACEOS_ALERT_WEBHOOK_URL', 'Process')
}
if ($WebhookUrl) {
    try {
        $Payload = [ordered]@{
            title = 'Workspace OS alert'
            fingerprint = $Outbox.fingerprint
            alert_count = $Outbox.alert_count
            alerts = $Outbox.alerts
        } | ConvertTo-Json -Depth 6
        Invoke-RestMethod -Method Post -Uri $WebhookUrl -ContentType 'application/json' -Body $Payload | Out-Null
        $Delivered.Add('webhook')
    }
    catch {
        $Failures.Add("webhook: $($_.Exception.Message)")
    }
}

if ($Delivered.Count -gt 0) {
    [ordered]@{
        schema_version = '1.0'
        updated_at = [DateTime]::UtcNow.ToString('o')
        last_delivered_fingerprint = $Outbox.fingerprint
        channels = @($Delivered)
        failures = @($Failures)
    } | ConvertTo-Json -Depth 4 | Set-Content -Encoding UTF8 -LiteralPath $StatePath
}
