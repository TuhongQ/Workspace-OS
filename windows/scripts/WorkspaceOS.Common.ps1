Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

function Invoke-WorkspaceOSPython {
    param([Parameter(Mandatory)][string[]]$Arguments)
    $Cli = Join-Path $PSScriptRoot '..\python\workspace_cli.py'
    $UserPython = Join-Path $env:LOCALAPPDATA 'Programs\Python\Python311\python.exe'
    if (Test-Path -LiteralPath $UserPython) {
        $PythonPath = $UserPython
    } else {
        $Python = Get-Command python -ErrorAction SilentlyContinue
        if (-not $Python) { throw '需要 Python 3.11+，但未找到 python 命令。' }
        $PythonPath = $Python.Source
    }
    & $PythonPath $Cli @Arguments
    if ($LASTEXITCODE -ne 0) { throw "Workspace OS 失败，退出码 $LASTEXITCODE" }
}
