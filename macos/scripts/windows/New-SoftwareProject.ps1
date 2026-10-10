[CmdletBinding(SupportsShouldProcess)]
param([Parameter(Mandatory)][string]$Name, [string]$WorkspacePath = (Join-Path $HOME 'Workspace'))
& (Join-Path $PSScriptRoot 'New-WorkspaceProject.ps1') -Type software -Name $Name -WorkspacePath $WorkspacePath -WhatIf:$WhatIfPreference

