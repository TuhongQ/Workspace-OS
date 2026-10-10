[CmdletBinding()]
param(
    [Parameter(Position = 0)][string]$Query = '',
    [string]$WorkspacePath = 'D:\Workspace',
    [string]$Project,
    [string]$Category,
    [string]$Extension,
    [int]$Limit = 50
)
. (Join-Path $PSScriptRoot 'WorkspaceOS.Common.ps1')
$Database = Join-Path $WorkspacePath '08_Indexes\Search\workspace-search.db'
$Arguments = @('search', $Query, '--database', $Database, '--limit', "$Limit")
if ($Project) { $Arguments += @('--project', $Project) }
if ($Category) { $Arguments += @('--category', $Category) }
if ($Extension) { $Arguments += @('--extension', $Extension) }
Invoke-WorkspaceOSPython -Arguments $Arguments
