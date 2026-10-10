param(
    [string]$WorkspacePath = 'D:\Workspace'
)

$ErrorActionPreference = 'Stop'
Add-Type -AssemblyName System.Windows.Forms
Add-Type -AssemblyName System.Drawing
[System.Windows.Forms.Application]::EnableVisualStyles()
if (-not ('WorkspaceRoundedButton' -as [type])) {
    Add-Type -ReferencedAssemblies 'System.Drawing.dll','System.Windows.Forms.dll' -TypeDefinition @'
using System;
using System.Drawing;
using System.Drawing.Drawing2D;
using System.Windows.Forms;

public class WorkspaceRoundedButton : Button {
    public Color BorderColor { get; set; }
    public int CornerRadius { get; set; }
    public WorkspaceRoundedButton() {
        BorderColor = Color.FromArgb(218, 221, 228);
        CornerRadius = 14;
        SetStyle(ControlStyles.AllPaintingInWmPaint | ControlStyles.OptimizedDoubleBuffer | ControlStyles.UserPaint, true);
        FlatStyle = FlatStyle.Flat;
        FlatAppearance.BorderSize = 0;
        Cursor = Cursors.Hand;
    }
    private GraphicsPath Rounded(Rectangle bounds, int radius) {
        int d = radius * 2;
        var path = new GraphicsPath();
        path.AddArc(bounds.X, bounds.Y, d, d, 180, 90);
        path.AddArc(bounds.Right - d, bounds.Y, d, d, 270, 90);
        path.AddArc(bounds.Right - d, bounds.Bottom - d, d, d, 0, 90);
        path.AddArc(bounds.X, bounds.Bottom - d, d, d, 90, 90);
        path.CloseFigure();
        return path;
    }
    protected override void OnPaint(PaintEventArgs e) {
        e.Graphics.SmoothingMode = SmoothingMode.AntiAlias;
        var rect = new Rectangle(0, 0, Width - 1, Height - 1);
        using (var path = Rounded(rect, CornerRadius))
        using (var brush = new SolidBrush(BackColor))
        using (var pen = new Pen(BorderColor)) {
            e.Graphics.FillPath(brush, path);
            e.Graphics.DrawPath(pen, path);
        }
        var flags = TextFormatFlags.VerticalCenter | TextFormatFlags.Left | TextFormatFlags.EndEllipsis;
        var textRect = new Rectangle(Padding.Left, 0, Width - Padding.Left - Padding.Right, Height);
        TextRenderer.DrawText(e.Graphics, Text, Font, textRect, ForeColor, flags);
    }
}
'@
}

$Root = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
$Cli = Join-Path $Root 'scripts\python\workspace_cli.py'
if (-not (Test-Path -LiteralPath $Cli)) {
    [System.Windows.Forms.MessageBox]::Show("找不到 Workspace OS 核心程序：$Cli", 'Workspace OS', 'OK', 'Error')
    exit 1
}

function Quote-Arg([string]$Value) {
    if ($null -eq $Value) { return '""' }
    return '"' + ($Value -replace '(\\*)"', '$1$1\"' -replace '(\\+)$', '$1$1') + '"'
}

function Invoke-Cli([string[]]$Arguments) {
    $psi = New-Object System.Diagnostics.ProcessStartInfo
    $psi.FileName = 'python'
    $psi.Arguments = (Quote-Arg $Cli) + ' ' + (($Arguments | ForEach-Object { Quote-Arg ([string]$_) }) -join ' ')
    $psi.WorkingDirectory = $Root
    $psi.UseShellExecute = $false
    $psi.CreateNoWindow = $true
    $psi.RedirectStandardOutput = $true
    $psi.RedirectStandardError = $true
    $p = New-Object System.Diagnostics.Process
    $p.StartInfo = $psi
    [void]$p.Start()
    $out = $p.StandardOutput.ReadToEnd()
    $err = $p.StandardError.ReadToEnd()
    $p.WaitForExit()
    return [pscustomobject]@{ ExitCode = $p.ExitCode; Output = $out; Error = $err }
}

$form = New-Object System.Windows.Forms.Form
$form.Text = 'Workspace OS 2.0 · 控制中心'
$form.Size = New-Object System.Drawing.Size(980, 830)
$form.MinimumSize = New-Object System.Drawing.Size(900, 650)
$form.StartPosition = 'CenterScreen'
$form.BackColor = [System.Drawing.Color]::FromArgb(242, 242, 247)
$form.Font = New-Object System.Drawing.Font('Microsoft YaHei UI', 9)

$title = New-Object System.Windows.Forms.Label
$title.Text = 'Workspace OS 2.0'
$title.Font = New-Object System.Drawing.Font('Microsoft YaHei UI', 20, [System.Drawing.FontStyle]::Bold)
$title.Location = New-Object System.Drawing.Point(24, 18)
$title.AutoSize = $true
$title.ForeColor = [System.Drawing.Color]::FromArgb(28, 28, 30)
$form.Controls.Add($title)

$sub = New-Object System.Windows.Forms.Label
$sub.Text = '轻松管理你的资料、搜索、备份与恢复'
$sub.ForeColor = [System.Drawing.Color]::FromArgb(110, 110, 115)
$sub.Location = New-Object System.Drawing.Point(28, 58)
$sub.AutoSize = $true
$form.Controls.Add($sub)

$pathLabel = New-Object System.Windows.Forms.Label
$pathLabel.Text = '工作区目录'
$pathLabel.Location = New-Object System.Drawing.Point(28, 92)
$pathLabel.AutoSize = $true
$pathLabel.ForeColor = [System.Drawing.Color]::FromArgb(58, 58, 60)
$form.Controls.Add($pathLabel)

$pathBox = New-Object System.Windows.Forms.TextBox
$pathBox.Text = $WorkspacePath
$pathBox.Location = New-Object System.Drawing.Point(110, 88)
$pathBox.Size = New-Object System.Drawing.Size(650, 28)
$pathBox.BorderStyle = 'FixedSingle'
$pathBox.BackColor = [System.Drawing.Color]::White
$pathBox.ForeColor = [System.Drawing.Color]::FromArgb(28, 28, 30)
$form.Controls.Add($pathBox)

$browse = New-Object System.Windows.Forms.Button
$browse.Text = '选择目录…'
$browse.Location = New-Object System.Drawing.Point(770, 86)
$browse.Size = New-Object System.Drawing.Size(120, 30)
$browse.FlatStyle = 'Flat'
$browse.BackColor = [System.Drawing.Color]::FromArgb(232, 240, 254)
$browse.ForeColor = [System.Drawing.Color]::FromArgb(0, 122, 255)
$browse.FlatAppearance.BorderColor = [System.Drawing.Color]::FromArgb(232, 240, 254)
$browse.Add_Click({
    $dialog = New-Object System.Windows.Forms.FolderBrowserDialog
    $dialog.Description = '选择 Workspace OS 工作区目录'
    $dialog.SelectedPath = $pathBox.Text
    if ($dialog.ShowDialog() -eq 'OK') { $pathBox.Text = $dialog.SelectedPath }
})
$form.Controls.Add($browse)

$log = New-Object System.Windows.Forms.TextBox
$log.Multiline = $true
$log.ScrollBars = 'Vertical'
$log.ReadOnly = $true
$log.BackColor = [System.Drawing.Color]::White
$log.ForeColor = [System.Drawing.Color]::FromArgb(58, 58, 60)
$log.BorderStyle = 'FixedSingle'
$log.Font = New-Object System.Drawing.Font('Consolas', 10)
$log.Location = New-Object System.Drawing.Point(28, 620)
$log.Size = New-Object System.Drawing.Size(862, 140)
$form.Controls.Add($log)

function Add-Log([string]$Text) {
    $log.AppendText("[$(Get-Date -Format 'HH:mm:ss')] $Text`r`n")
    $log.SelectionStart = $log.TextLength
    $log.ScrollToCaret()
}

function Run-Action([string]$Name, [string[]]$CliArgs, [string]$OpenPath) {
    try {
        Add-Log "开始：$Name"
        $result = Invoke-Cli $CliArgs
        if ($result.Output.Trim()) { Add-Log ($result.Output.Trim()) }
        if ($result.Error.Trim()) { Add-Log ('提示：' + $result.Error.Trim()) }
        if ($result.ExitCode -eq 0) {
            Add-Log "完成：$Name"
            if ($OpenPath -and (Test-Path -LiteralPath $OpenPath)) { Start-Process $OpenPath }
        } else { Add-Log "失败：$Name（退出码 $($result.ExitCode)）" }
    } catch { Add-Log "失败：$Name · $($_.Exception.Message)" }
}

function WorkspaceArgs([string[]]$Extra) {
    if ($Extra.Count -eq 0) { return @('--workspace', $pathBox.Text) }
    if ($Extra.Count -eq 1) { return @($Extra[0], '--workspace', $pathBox.Text) }
    return @($Extra[0], '--workspace', $pathBox.Text) + $Extra[1..($Extra.Count - 1)]
}
function Add-Section([string]$Text, [int]$X, [int]$Y, [int]$W, [int]$H) {
    $g = New-Object System.Windows.Forms.Label
    $g.Text = $Text
    $g.Location = New-Object System.Drawing.Point($X, $Y)
    $g.Size = New-Object System.Drawing.Size($W, 20)
    $g.Font = New-Object System.Drawing.Font('Microsoft YaHei UI', 9, [System.Drawing.FontStyle]::Bold)
    $g.ForeColor = [System.Drawing.Color]::FromArgb(110, 110, 115)
    $g.BackColor = [System.Drawing.Color]::FromArgb(242, 242, 247)
    $form.Controls.Add($g)
}
function Add-ActionButton([string]$Text, [int]$X, [int]$Y, [scriptblock]$Action) {
    $b = New-Object WorkspaceRoundedButton
    $b.Text = $Text + '   ›'
    $b.Location = New-Object System.Drawing.Point($X, $Y)
    $b.Size = New-Object System.Drawing.Size(270, 54)
    $b.Font = New-Object System.Drawing.Font('Microsoft YaHei UI', 10)
    $b.BackColor = [System.Drawing.Color]::White
    $b.ForeColor = [System.Drawing.Color]::FromArgb(0, 122, 255)
    $b.BorderColor = [System.Drawing.Color]::FromArgb(218, 221, 228)
    $b.Padding = New-Object System.Windows.Forms.Padding(18, 0, 12, 0)
    $b.Add_Click($Action)
    $form.Controls.Add($b)
}

Add-Section '开始使用' 28 116 885 20

Add-ActionButton '初始化工作区' 28 142 { Run-Action '初始化工作区' @('init','--path',$pathBox.Text) $null }
Add-ActionButton '整理收件箱（预览）' 324 142 { Run-Action '扫描收件箱（预览）' (WorkspaceArgs @('scan-inbox')) $null }
Add-ActionButton '执行收件箱整理' 620 142 { Run-Action '执行收件箱整理' (WorkspaceArgs @('scan-inbox','--apply')) $null }

Add-Section '查找与保护资料' 28 224 885 20

$query = New-Object System.Windows.Forms.TextBox
$query.Text = '输入要搜索的关键词'
$query.ForeColor = [System.Drawing.Color]::FromArgb(142, 142, 147)
$query.Location = New-Object System.Drawing.Point(28, 250)
$query.Size = New-Object System.Drawing.Size(620, 38)
$query.BorderStyle = 'FixedSingle'
$query.BackColor = [System.Drawing.Color]::White
$form.Controls.Add($query)
$query.Add_GotFocus({ if ($query.Text -eq '输入要搜索的关键词') { $query.Text=''; $query.ForeColor=[System.Drawing.Color]::FromArgb(28, 28, 30) } })
$searchButton = New-Object WorkspaceRoundedButton
$searchButton.Text = '搜索资料'
$searchButton.Location = New-Object System.Drawing.Point(666, 250)
$searchButton.Size = New-Object System.Drawing.Size(224, 38)
$searchButton.BackColor = [System.Drawing.Color]::FromArgb(0, 122, 255)
$searchButton.ForeColor = [System.Drawing.Color]::White
$searchButton.BorderColor = [System.Drawing.Color]::FromArgb(0, 122, 255)
$searchButton.Padding = New-Object System.Windows.Forms.Padding(16, 0, 10, 0)
$searchButton.Add_Click({
    if ([string]::IsNullOrWhiteSpace($query.Text) -or $query.Text -eq '输入要搜索的关键词') { Add-Log '请先输入搜索关键词'; return }
    Run-Action "搜索：$($query.Text)" (WorkspaceArgs @('search',$query.Text,'--database',(Join-Path $pathBox.Text '08_Indexes\workspace-search.db'),'--limit','50')) $null
})
$form.Controls.Add($searchButton)

Add-ActionButton '更新搜索索引' 28 306 { Run-Action '维护搜索索引' (WorkspaceArgs @('search-maintain','--database',(Join-Path $pathBox.Text '08_Indexes\workspace-search.db'),'--content','--output',(Join-Path $pathBox.Text '08_Indexes\search-maintain.json'))) $null }
Add-ActionButton '快照预览' 324 306 { Run-Action '创建快照（预览）' (WorkspaceArgs @('snapshot','--destination',(Join-Path $pathBox.Text '06_Release\Snapshots'))) $null }
Add-ActionButton '创建快照' 620 306 { Run-Action '执行快照' (WorkspaceArgs @('snapshot','--destination',(Join-Path $pathBox.Text '06_Release\Snapshots'),'--apply')) $null }

Add-Section '维护与恢复' 28 386 885 20
Add-ActionButton '系统健康检查' 28 412 { Run-Action '健康检查' (WorkspaceArgs @('doctor')) $null }
Add-ActionButton '安全检查' 324 412 { Run-Action '安全审计' (WorkspaceArgs @('security-audit')) $null }
Add-ActionButton '查看提醒与告警' 620 412 { Run-Action '查看告警' (WorkspaceArgs @('alerts')) $null }
Add-ActionButton '查看恢复状态' 28 482 { Run-Action '恢复准备度' (WorkspaceArgs @('recovery-readiness','--snapshots',(Join-Path $pathBox.Text '06_Release\Snapshots'),'--output',(Join-Path $pathBox.Text '08_Indexes\recovery-readiness.json'))) $null }
Add-ActionButton '恢复到新文件夹' 324 482 {
    $sd = New-Object System.Windows.Forms.FolderBrowserDialog
    $sd.Description = '选择要恢复的快照目录'
    $sd.SelectedPath = Join-Path $pathBox.Text '06_Release\Snapshots'
    if ($sd.ShowDialog() -ne 'OK') { return }
    $dd = New-Object System.Windows.Forms.FolderBrowserDialog
    $dd.Description = '选择恢复目标目录（建议使用临时目录）'
    $dd.SelectedPath = Join-Path (Split-Path $pathBox.Text) 'WorkspaceRestoreTests\ManualRestore'
    if ($dd.ShowDialog() -ne 'OK') { return }
    Run-Action '恢复快照' @('restore',$sd.SelectedPath,'--destination',$dd.SelectedPath,'--apply') $null
}

$open = New-Object WorkspaceRoundedButton
$open.Text = '打开工作区文件夹   ›'
$open.Location = New-Object System.Drawing.Point(620, 482)
$open.Size = New-Object System.Drawing.Size(270, 54)
$open.Font = New-Object System.Drawing.Font('Microsoft YaHei UI', 10)
$open.BackColor = [System.Drawing.Color]::White
$open.ForeColor = [System.Drawing.Color]::FromArgb(0, 122, 255)
$open.BorderColor = [System.Drawing.Color]::FromArgb(218, 221, 228)
$open.Padding = New-Object System.Windows.Forms.Padding(18, 0, 12, 0)
$open.Add_Click({ if (Test-Path -LiteralPath $pathBox.Text) { Start-Process explorer.exe $pathBox.Text } else { Add-Log '工作区目录不存在，请先初始化或选择目录' } })
$form.Controls.Add($open)
$openDocs = New-Object WorkspaceRoundedButton
$openDocs.Text = '打开完整使用说明   ›'
$openDocs.Location = New-Object System.Drawing.Point(324, 552)
$openDocs.Size = New-Object System.Drawing.Size(270, 36)
$openDocs.Font = New-Object System.Drawing.Font('Microsoft YaHei UI', 9)
$openDocs.BackColor = [System.Drawing.Color]::FromArgb(232, 240, 254)
$openDocs.ForeColor = [System.Drawing.Color]::FromArgb(0, 122, 255)
$openDocs.BorderColor = [System.Drawing.Color]::FromArgb(232, 240, 254)
$openDocs.Padding = New-Object System.Windows.Forms.Padding(14, 0, 8, 0)
$openDocs.Add_Click({ Start-Process (Join-Path $Root 'docs\使用说明与功能介绍.md') })
$form.Controls.Add($openDocs)

Add-Log '控制中心已启动。请选择工作区，然后按按钮操作。'
Add-Log '带“预览”的操作不会移动或覆盖资料；确认后可使用命令行中的 --apply。'
[void]$form.ShowDialog()
