[CmdletBinding(SupportsShouldProcess)]
param(
    [string]$ComputerPath = 'D:\Workspace',
    [string]$NasPath = 'W:\',
    [string]$OutputPath = 'D:\Workspace\08_Indexes\file-locations.html',
    [string]$NasOutputPath = '',
    [switch]$RefreshNas
)
$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot 'WorkspaceOS.Common.ps1')
if (-not (Test-Path -LiteralPath $ComputerPath)) { throw "电脑工作区不存在：$ComputerPath" }
if (-not (Test-Path -LiteralPath $NasPath)) { throw "NAS 工作区不可访问：$NasPath" }
if ([string]::IsNullOrWhiteSpace($NasOutputPath)) {
    $NasOutputPath = Join-Path $NasPath '08_Indexes\file-locations.html'
}
if ($PSCmdlet.ShouldProcess($OutputPath, '更新文件位置网页快照')) {
    $Arguments = @('locations','--computer',$ComputerPath,'--nas',$NasPath,'--output',$OutputPath)
    if ($RefreshNas) { $Arguments += '--refresh-nas' }
    Invoke-WorkspaceOSPython -Arguments $Arguments
    $NasOutputDirectory = Split-Path -Parent $NasOutputPath
    if (-not (Test-Path -LiteralPath $NasOutputDirectory)) {
        New-Item -ItemType Directory -Path $NasOutputDirectory -Force | Out-Null
    }
    Copy-Item -LiteralPath $OutputPath -Destination $NasOutputPath -Force
    $LocalJsonPath = [IO.Path]::ChangeExtension($OutputPath, '.json')
    $NasJsonPath = [IO.Path]::ChangeExtension($NasOutputPath, '.json')
    Copy-Item -LiteralPath $LocalJsonPath -Destination $NasJsonPath -Force
    Start-Process $NasOutputPath
}
