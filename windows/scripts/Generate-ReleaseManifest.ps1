[CmdletBinding(SupportsShouldProcess)]
param([Parameter(Mandatory)][string]$Path, [string]$Version = 'unknown')
. (Join-Path $PSScriptRoot 'WorkspaceOS.Common.ps1')
if ($PSCmdlet.ShouldProcess($Path, '生成发布清单')) { Invoke-WorkspaceOSPython -Arguments @('manifest', $Path, '--release-version', $Version) }

