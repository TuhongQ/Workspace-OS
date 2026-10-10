[CmdletBinding()]
param(
    [string]$WorkspacePath = 'D:\Workspace',
    [ValidateRange(5, 60)]
    [int]$ProbeTimeoutSeconds = 15
)

$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot 'WorkspaceOS.Common.ps1')
$Probe = Join-Path $WorkspacePath '08_Indexes\Security\security-posture-probe.json'
$Report = Join-Path $WorkspacePath '08_Indexes\Security\security-posture.json'
$Worker = Join-Path $PSScriptRoot 'Probe-WorkspaceSecurityPosture.ps1'
$ProbeTemporary = Join-Path `
    (Split-Path -Parent $Probe) `
    ('.security-posture-worker.{0}.tmp' -f [guid]::NewGuid().ToString('N'))

$ArgumentValues = @(
    '-NoProfile',
    '-ExecutionPolicy', 'Bypass',
    '-File', $Worker,
    '-WorkspacePath', $WorkspacePath,
    '-OutputPath', $ProbeTemporary
)
$Arguments = ($ArgumentValues | ForEach-Object {
    if ($_ -match '\s') { '"{0}"' -f ($_ -replace '"', '\"') } else { $_ }
}) -join ' '

try {
    $Process = Start-Process `
        -FilePath (Join-Path $PSHOME 'powershell.exe') `
        -ArgumentList $Arguments `
        -WindowStyle Hidden `
        -PassThru
    if (-not $Process.WaitForExit($ProbeTimeoutSeconds * 1000)) {
        $Process.Kill()
        $null = $Process.WaitForExit(1000)
        $Fallback = [ordered]@{
            schema_version = '1.0'
            generated_at = [DateTime]::UtcNow.ToString('o')
            platform = 'windows'
            probe_status = 'timeout'
            privacy_mode = 'sid-only-no-user-identities'
            protected_paths = @()
            volume = @{
                mount_point = [IO.Path]::GetPathRoot([IO.Path]::GetFullPath($WorkspacePath))
                query_status = 'timeout'
                query_code = 'PROBE_TIMEOUT'
                filesystem = $null
                volume_status = $null
                protection_status = $null
                encryption_percentage = $null
                encryption_method = $null
                evidence_source = 'none'
                evidence_generated_at = $null
                evidence_age_hours = $null
                live_query_code = 'PROBE_TIMEOUT'
                cached_evidence_status = 'not-checked'
                volume_id_hash = $null
            }
        }
        $Fallback | ConvertTo-Json -Depth 5 | Set-Content -LiteralPath $ProbeTemporary -Encoding UTF8
    }
    elseif ($Process.ExitCode -ne 0 -or -not (Test-Path -LiteralPath $ProbeTemporary -PathType Leaf)) {
        $Fallback = [ordered]@{
            schema_version = '1.0'
            generated_at = [DateTime]::UtcNow.ToString('o')
            platform = 'windows'
            probe_status = 'failed'
            privacy_mode = 'sid-only-no-user-identities'
            protected_paths = @()
            volume = @{
                mount_point = [IO.Path]::GetPathRoot([IO.Path]::GetFullPath($WorkspacePath))
                query_status = 'failed'
                query_code = 'PROBE_FAILED'
                filesystem = $null
                volume_status = $null
                protection_status = $null
                encryption_percentage = $null
                encryption_method = $null
                evidence_source = 'none'
                evidence_generated_at = $null
                evidence_age_hours = $null
                live_query_code = 'PROBE_FAILED'
                cached_evidence_status = 'not-checked'
                volume_id_hash = $null
            }
        }
        $Fallback | ConvertTo-Json -Depth 5 | Set-Content -LiteralPath $ProbeTemporary -Encoding UTF8
    }
    Move-Item -LiteralPath $ProbeTemporary -Destination $Probe -Force
}
finally {
    Remove-Item -LiteralPath $ProbeTemporary -Force -ErrorAction SilentlyContinue
}

Invoke-WorkspaceOSPython -Arguments @(
    'security-posture',
    '--workspace', $WorkspacePath,
    '--probe', $Probe,
    '--output', $Report
)

