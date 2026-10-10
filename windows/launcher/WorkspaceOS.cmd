@echo off
setlocal
powershell.exe -NoProfile -ExecutionPolicy Bypass -STA -File "%~dp0scripts\windows\WorkspaceOS-ControlCenter-WPF.ps1" %*
endlocal
