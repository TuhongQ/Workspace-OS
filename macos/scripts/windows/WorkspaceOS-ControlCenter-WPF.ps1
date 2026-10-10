param([string]$WorkspacePath = 'D:\Workspace')

$ErrorActionPreference = 'Stop'
Add-Type -AssemblyName PresentationFramework
Add-Type -AssemblyName PresentationCore
Add-Type -AssemblyName WindowsBase
Add-Type -AssemblyName System.Windows.Forms
Add-Type -AssemblyName Microsoft.VisualBasic

$Root = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
$Cli = Join-Path $Root 'scripts\python\workspace_cli.py'
$BundledPython = Join-Path $Root 'runtime\python\python.exe'
$PythonExecutable = if (Test-Path -LiteralPath $BundledPython) { $BundledPython } else { 'python' }
if (-not (Test-Path -LiteralPath $Cli)) { throw "找不到核心程序：$Cli" }
$SettingsDirectory = Join-Path $env:APPDATA 'WorkspaceOS'
$SettingsPath = Join-Path $SettingsDirectory 'control-center-settings.json'
$Settings = @{}
if (Test-Path -LiteralPath $SettingsPath) { try { $Settings = Get-Content -LiteralPath $SettingsPath -Raw -Encoding utf8 | ConvertFrom-Json } catch { $Settings = @{} } }
$script:NasPath = if ($Settings.nas_path) { [string]$Settings.nas_path } else { 'W:\' }
$script:NasAutoDetected = $false
$script:NasConfiguredPath = $script:NasPath
# 映射盘、旧 IP 或登录会话在不同电脑上可能失效；即使设置文件里有旧地址，
# 也只读探测当前可用的 SMB 入口并临时回退，避免资源管理器可用而控制中心报不可访问。
if (-not (Test-Path -LiteralPath $script:NasPath)) {
    $knownNasFallbacks = @()
    try {
        $knownNasFallbacks += @(Get-SmbMapping -ErrorAction Stop |
            Where-Object { $_.Status -eq 'OK' -and $_.RemotePath -like '*\Workspace' } |
            Select-Object -ExpandProperty RemotePath)
    } catch { }
    # 常用入口只作为最后兜底，且仍必须通过 Test-Path 验证。
    $knownNasFallbacks += '\\192.168.1.9\Workspace'
    $knownNasFallbacks += '\\192.168.100.110\Workspace'
    $knownNasFallbacks = @($knownNasFallbacks | Where-Object { $_ -and $_ -ne $script:NasPath } | Select-Object -Unique)
    foreach ($candidate in $knownNasFallbacks) {
        if (Test-Path -LiteralPath $candidate) { $script:NasPath = $candidate; $script:NasAutoDetected = $true; break }
    }
}

[xml]$Xaml = @'
<Window xmlns="http://schemas.microsoft.com/winfx/2006/xaml/presentation"
        xmlns:x="http://schemas.microsoft.com/winfx/2006/xaml"
        Title="Workspace OS 2.0 · NEXUS Control Center" Width="980" Height="720" MinWidth="900" MinHeight="650"
        WindowStartupLocation="CenterScreen" Background="#0B1F46" FontFamily="Segoe UI">
  <Window.Resources>
    <Style x:Key="SectionTitle" TargetType="TextBlock">
      <Setter Property="FontSize" Value="13"/><Setter Property="FontWeight" Value="SemiBold"/>
      <Setter Property="Foreground" Value="#94A3B8"/><Setter Property="Margin" Value="2,0,0,10"/>
    </Style>
    <Style x:Key="CardButton" TargetType="Button">
      <Setter Property="Height" Value="54"/><Setter Property="Margin" Value="0,0,10,0"/>
      <Setter Property="Padding" Value="16,7"/><Setter Property="HorizontalContentAlignment" Value="Left"/>
      <Setter Property="Background" Value="#173B70"/><Setter Property="Foreground" Value="#F8FAFC"/><Setter Property="BorderThickness" Value="0"/><Setter Property="BorderBrush" Value="Transparent"/>
      <Setter Property="Cursor" Value="Hand"/>
      <Setter Property="Template"><Setter.Value>
        <ControlTemplate TargetType="Button"><Border x:Name="Card" Background="{TemplateBinding Background}" CornerRadius="16" Padding="{TemplateBinding Padding}">
          <Border.Effect><DropShadowEffect BlurRadius="18" ShadowDepth="3" Direction="270" Color="#020617" Opacity="0.30"/></Border.Effect>
          <ContentPresenter HorizontalAlignment="{TemplateBinding HorizontalContentAlignment}" VerticalAlignment="Center"/>
        </Border><ControlTemplate.Triggers><Trigger Property="IsMouseOver" Value="True"><Setter TargetName="Card" Property="Background" Value="#1B4C82"/></Trigger><Trigger Property="IsPressed" Value="True"><Setter TargetName="Card" Property="Background" Value="#2563A5"/></Trigger></ControlTemplate.Triggers>
        </ControlTemplate>
      </Setter.Value></Setter>
    </Style>
    <Style x:Key="PrimaryButton" TargetType="Button" BasedOn="{StaticResource CardButton}">
      <Setter Property="Background" Value="#2563EB"/><Setter Property="Foreground" Value="White"/>
      <Setter Property="HorizontalContentAlignment" Value="Center"/><Setter Property="Margin" Value="0"/>
      <Setter Property="Template"><Setter.Value>
        <ControlTemplate TargetType="Button"><Border x:Name="Card" Background="{TemplateBinding Background}" CornerRadius="14" Padding="{TemplateBinding Padding}">
          <ContentPresenter HorizontalAlignment="Center" VerticalAlignment="Center"/>
        </Border><ControlTemplate.Triggers><Trigger Property="IsMouseOver" Value="True"><Setter TargetName="Card" Property="Background" Value="#006FE6"/></Trigger><Trigger Property="IsPressed" Value="True"><Setter TargetName="Card" Property="Background" Value="#0065D1"/></Trigger></ControlTemplate.Triggers>
        </ControlTemplate>
      </Setter.Value></Setter>
    </Style>
    <Style x:Key="PathBox" TargetType="TextBox"><Setter Property="BorderThickness" Value="0"/><Setter Property="Background" Value="Transparent"/><Setter Property="FontSize" Value="14"/><Setter Property="Foreground" Value="#F8FAFC"/><Setter Property="CaretBrush" Value="#67E8F9"/><Setter Property="VerticalContentAlignment" Value="Center"/></Style>
  </Window.Resources>
  <Grid Margin="26,18,26,18">
    <Grid.RowDefinitions><RowDefinition Height="Auto"/><RowDefinition Height="52"/><RowDefinition Height="Auto"/><RowDefinition Height="Auto"/><RowDefinition Height="Auto"/><RowDefinition Height="140"/></Grid.RowDefinitions>
    <DockPanel Grid.Row="0" Margin="0,0,0,8"><Viewbox Width="34" Height="34" DockPanel.Dock="Left" Margin="0,0,10,0"><Grid Width="48" Height="48"><Path Data="M24,2 L43,13 L43,35 L24,46 L5,35 L5,13 Z" Fill="#182342" Stroke="#22D3EE" StrokeThickness="2"/><Path Data="M15,34 L15,14 L33,34 L33,14" Fill="Transparent" Stroke="#A78BFA" StrokeThickness="4" StrokeStartLineCap="Round" StrokeEndLineCap="Round" StrokeLineJoin="Round"/></Grid></Viewbox><StackPanel><TextBlock Text="NEXUS" FontSize="21" FontWeight="SemiBold" Foreground="#F8FAFC"/><TextBlock Text="WORKSPACE OS 2.0  ·  DIGITAL ASSET CONTROL" FontSize="10" Foreground="#67E8F9" Margin="2,0,0,0"/></StackPanel><Border DockPanel.Dock="Right" Background="#123047" CornerRadius="10" Padding="10,4" VerticalAlignment="Center"><TextBlock Text="● ONLINE" Foreground="#67E8F9" FontSize="10" FontWeight="SemiBold"/></Border></DockPanel>
    <Grid Grid.Row="1" Margin="0,0,0,8"><Grid.ColumnDefinitions><ColumnDefinition Width="*"/><ColumnDefinition Width="172"/></Grid.ColumnDefinitions><Border Background="White" CornerRadius="16" Padding="16,6"><Grid><Grid.ColumnDefinitions><ColumnDefinition Width="74"/><ColumnDefinition Width="*"/></Grid.ColumnDefinitions><TextBlock Text="工作区" Foreground="#6E6E73" VerticalAlignment="Center" FontWeight="SemiBold"/><TextBox x:Name="WorkspaceBox" Grid.Column="1" Style="{StaticResource PathBox}"/></Grid></Border><Button x:Name="BrowseButton" Grid.Column="1" Style="{StaticResource PrimaryButton}" Height="42" Padding="8,4" Margin="10,0,0,0" Content="选择目录"/></Grid>
    <StackPanel Grid.Row="2" Margin="0,0,0,12"><TextBlock Text="开始使用" Style="{StaticResource SectionTitle}" Margin="2,0,0,6"/><UniformGrid Columns="4"><Button x:Name="InitButton" Style="{StaticResource CardButton}"><StackPanel><TextBlock Text="初始化工作区" FontSize="13" FontWeight="SemiBold" Foreground="#1D1D1F"/><TextBlock Text="创建标准目录" FontSize="10" Foreground="#8E8E93" Margin="0,2,0,0"/></StackPanel></Button><Button x:Name="InboxPreviewButton" Style="{StaticResource CardButton}"><StackPanel><TextBlock Text="整理收件箱" FontSize="13" FontWeight="SemiBold" Foreground="#1D1D1F"/><TextBlock Text="先预览建议分类" FontSize="10" Foreground="#8E8E93" Margin="0,2,0,0"/></StackPanel></Button><Button x:Name="InboxApplyButton" Style="{StaticResource CardButton}"><StackPanel><TextBlock Text="执行收件箱整理" FontSize="13" FontWeight="SemiBold" Foreground="#1D1D1F"/><TextBlock Text="确认后移动文件" FontSize="10" Foreground="#8E8E93" Margin="0,2,0,0"/></StackPanel></Button><Button x:Name="OpenWebButton" Style="{StaticResource CardButton}" Margin="0"><StackPanel><TextBlock Text="打开网页版" FontSize="13" FontWeight="SemiBold" Foreground="#007AFF"/><TextBlock Text="Workspace OS 看板" FontSize="10" Foreground="#8E8E93" Margin="0,2,0,0"/></StackPanel></Button></UniformGrid></StackPanel>
    <StackPanel Grid.Row="3" Margin="0,0,0,12"><TextBlock Text="查找与保护资料" Style="{StaticResource SectionTitle}" Margin="2,0,0,6"/><Border Background="White" CornerRadius="16" Padding="12,6" Margin="0,0,0,8"><Grid><Grid.ColumnDefinitions><ColumnDefinition Width="135"/><ColumnDefinition Width="380"/><ColumnDefinition Width="*"/></Grid.ColumnDefinitions><StackPanel VerticalAlignment="Center"><TextBlock Text="搜索资料" FontSize="13" FontWeight="SemiBold" Foreground="#1D1D1F"/><TextBlock Text="输入关键词快速查找" FontSize="10" Foreground="#8E8E93" Margin="0,1,0,0"/></StackPanel><Border Grid.Column="1" Background="#F2F2F7" CornerRadius="10" Height="36" Margin="0,0,10,0"><TextBox x:Name="SearchBox" Style="{StaticResource PathBox}" Margin="10,0" Text="输入要搜索的关键词" Foreground="#8E8E93"/></Border><Button x:Name="SearchButton" Grid.Column="2" Style="{StaticResource PrimaryButton}" Height="36" Content="搜索"/></Grid></Border><UniformGrid Columns="3"><Button x:Name="IndexButton" Style="{StaticResource CardButton}"><StackPanel><TextBlock Text="更新搜索索引" FontSize="13" FontWeight="SemiBold" Foreground="#1D1D1F"/><TextBlock Text="新增或修改文件后执行" FontSize="10" Foreground="#8E8E93" Margin="0,2,0,0"/></StackPanel></Button><Button x:Name="SnapshotPreviewButton" Style="{StaticResource CardButton}"><StackPanel><TextBlock Text="快照预览" FontSize="13" FontWeight="SemiBold" Foreground="#1D1D1F"/><TextBlock Text="查看将要备份的内容" FontSize="10" Foreground="#8E8E93" Margin="0,2,0,0"/></StackPanel></Button><Button x:Name="SnapshotButton" Style="{StaticResource CardButton}" Margin="0"><StackPanel><TextBlock Text="创建快照" FontSize="13" FontWeight="SemiBold" Foreground="#1D1D1F"/><TextBlock Text="保存当前可恢复副本" FontSize="10" Foreground="#8E8E93" Margin="0,2,0,0"/></StackPanel></Button></UniformGrid></StackPanel>
    <StackPanel Grid.Row="4" Margin="0,0,0,10"><TextBlock Text="维护与恢复" Style="{StaticResource SectionTitle}" Margin="2,0,0,6"/><UniformGrid Columns="3"><Button x:Name="DoctorButton" Style="{StaticResource CardButton}"><StackPanel><TextBlock Text="系统健康检查" FontSize="13" FontWeight="SemiBold" Foreground="#1D1D1F"/><TextBlock Text="检查工作区状态" FontSize="10" Foreground="#8E8E93" Margin="0,2,0,0"/></StackPanel></Button><Button x:Name="SecurityButton" Style="{StaticResource CardButton}"><StackPanel><TextBlock Text="安全检查" FontSize="13" FontWeight="SemiBold" Foreground="#1D1D1F"/><TextBlock Text="查看敏感信息风险" FontSize="10" Foreground="#8E8E93" Margin="0,2,0,0"/></StackPanel></Button><Button x:Name="AlertsButton" Style="{StaticResource CardButton}" Margin="0"><StackPanel><TextBlock Text="提醒与告警" FontSize="13" FontWeight="SemiBold" Foreground="#1D1D1F"/><TextBlock Text="查看需要处理的事项" FontSize="10" Foreground="#8E8E93" Margin="0,2,0,0"/></StackPanel></Button></UniformGrid><UniformGrid Columns="3" Margin="0,8,0,0"><Button x:Name="ReadinessButton" Style="{StaticResource CardButton}"><StackPanel><TextBlock Text="恢复状态" FontSize="13" FontWeight="SemiBold" Foreground="#1D1D1F"/><TextBlock Text="确认备份是否可恢复" FontSize="10" Foreground="#8E8E93" Margin="0,2,0,0"/></StackPanel></Button><Button x:Name="RestoreButton" Style="{StaticResource CardButton}"><StackPanel><TextBlock Text="恢复到新文件夹" FontSize="13" FontWeight="SemiBold" Foreground="#1D1D1F"/><TextBlock Text="始终避免覆盖原资料" FontSize="10" Foreground="#8E8E93" Margin="0,2,0,0"/></StackPanel></Button><Button x:Name="OpenButton" Style="{StaticResource CardButton}" Margin="0"><StackPanel><TextBlock Text="打开工作区" FontSize="13" FontWeight="SemiBold" Foreground="#1D1D1F"/><TextBlock Text="在资源管理器中查看文件" FontSize="10" Foreground="#8E8E93" Margin="0,2,0,0"/></StackPanel></Button></UniformGrid></StackPanel>
    <Border x:Name="LogPanel" Grid.Row="5" Background="#111827" BorderThickness="0" CornerRadius="16" Padding="14"><Grid><Grid.RowDefinitions><RowDefinition Height="Auto"/><RowDefinition Height="*"/></Grid.RowDefinitions><DockPanel><TextBlock Text="活动日志  /  LIVE" FontSize="12" FontWeight="SemiBold" Foreground="#C7D2FE"/><Button x:Name="HelpButton" Content="使用说明" Foreground="#7DD3FC" Background="Transparent" BorderThickness="0" DockPanel.Dock="Right" Cursor="Hand" Padding="8,1"/><Button x:Name="NasSettingsButton" Content="NAS 设置" Foreground="#7DD3FC" Background="Transparent" BorderThickness="0" DockPanel.Dock="Right" Cursor="Hand" Padding="8,1"/></DockPanel><TextBox x:Name="LogBox" Grid.Row="1" Margin="0,8,0,0" IsReadOnly="True" BorderThickness="0" Background="Transparent" Foreground="#D1FAE5" FontFamily="Consolas" FontSize="10" TextWrapping="Wrap" VerticalScrollBarVisibility="Auto"/></Grid></Border>
  </Grid>
</Window>
'@

$Reader = New-Object System.Xml.XmlNodeReader $Xaml
$Window = [Windows.Markup.XamlReader]::Load($Reader)
# 将旧版 XAML 中的浅色控件统一映射到网页版 NEXUS 深色主题，避免修改任何按钮事件和核心功能。
function Get-VisualDescendants([System.Windows.DependencyObject]$Parent) {
    if ($null -eq $Parent) { return }
    $count = [System.Windows.Media.VisualTreeHelper]::GetChildrenCount($Parent)
    for ($i = 0; $i -lt $count; $i++) {
        $child = [System.Windows.Media.VisualTreeHelper]::GetChild($Parent, $i)
        $child
        Get-VisualDescendants $child
    }
}
$darkSurface = [System.Windows.Media.BrushConverter]::new().ConvertFromString('#12305C')
$darkInput = [System.Windows.Media.BrushConverter]::new().ConvertFromString('#102A52')
$lightText = [System.Windows.Media.BrushConverter]::new().ConvertFromString('#E2E8F0')
$mutedText = [System.Windows.Media.BrushConverter]::new().ConvertFromString('#94A3B8')
$accentText = [System.Windows.Media.BrushConverter]::new().ConvertFromString('#67E8F9')
$Window.Background = [System.Windows.Media.BrushConverter]::new().ConvertFromString('#0B1F46')
foreach ($node in @(Get-VisualDescendants $Window)) {
    if ($node -is [System.Windows.Controls.Border]) {
        $color = if ($node.Background -and $node.Background.ToString() -in @('#FFFFFFFF','#FFF5F5F7','#FFF2F2F7')) { $darkSurface } else { $node.Background }
        if ($node.Background -and $node.Background.ToString() -eq '#FFF2F2F7') { $color = $darkInput }
        if ($color) { $node.Background = $color }
    } elseif ($node -is [System.Windows.Controls.TextBlock]) {
        $current = if ($node.Foreground) { $node.Foreground.ToString() } else { '' }
        if ($current -in @('#FF1D1D1F','#FF6E6E73','#FF8E8E93')) { $node.Foreground = if ($current -eq '#FF6E6E73') { $mutedText } else { $lightText } }
        if ($node.Text -like '*打开网页版*' -or $node.Text -like '*NEXUS*') { $node.Foreground = $accentText }
    }
}
# 内容控件使用显式高对比度，避免系统主题或 WPF 默认样式把文字回退成黑色。
foreach ($node in @(Get-VisualDescendants $Window)) {
    if ($node -is [System.Windows.Controls.Button]) { $node.Foreground = $lightText }
    elseif ($node -is [System.Windows.Controls.TextBox]) { $node.Foreground = $lightText }
    elseif ($node -is [System.Windows.Controls.TextBlock]) {
        if ($node.Text -notlike '*ONLINE*' -and $node.Text -notlike '*NEXUS*' -and $node.Text -notlike '*LIVE*') { $node.Foreground = $lightText }
    }
}
# ContentRendered 时再次应用，确保 ContentPresenter 生成后的按钮文字也继承高对比度颜色。
$Window.Add_ContentRendered({
    $bright = [System.Windows.Media.BrushConverter]::new().ConvertFromString('#F8FAFC')
    $cyan = [System.Windows.Media.BrushConverter]::new().ConvertFromString('#67E8F9')
    $inputBlue = [System.Windows.Media.BrushConverter]::new().ConvertFromString('#082653')
    $inputEdge = [System.Windows.Media.BrushConverter]::new().ConvertFromString('#4AA3DF')
    $windowGradient = [System.Windows.Media.LinearGradientBrush]::new()
    $windowGradient.StartPoint = [System.Windows.Point]::new(0,0)
    $windowGradient.EndPoint = [System.Windows.Point]::new(1,1)
    [void]$windowGradient.GradientStops.Add([System.Windows.Media.GradientStop]::new([System.Windows.Media.ColorConverter]::ConvertFromString('#071A46'),0.0))
    [void]$windowGradient.GradientStops.Add([System.Windows.Media.GradientStop]::new([System.Windows.Media.ColorConverter]::ConvertFromString('#182A68'),0.46))
    [void]$windowGradient.GradientStops.Add([System.Windows.Media.GradientStop]::new([System.Windows.Media.ColorConverter]::ConvertFromString('#123B63'),1.0))
    $Window.Background = $windowGradient
    foreach ($item in @(Get-VisualDescendants $Window)) {
        if ($item -is [System.Windows.Controls.Button]) { $item.Foreground = $bright }
        elseif ($item -is [System.Windows.Controls.TextBox]) { $item.Foreground = $bright; $item.Background = $inputBlue; $item.BorderBrush = $inputEdge; $item.BorderThickness = [System.Windows.Thickness]::new(1); $item.CaretBrush = $cyan; [System.Windows.Documents.TextElement]::SetForeground($item, $bright) }
        elseif ($item -is [System.Windows.Controls.Border]) {
            $brushName = if ($item.Background) { $item.Background.ToString() } else { '' }
            if ($brushName -in @('#FFFFFFFF','#FFF2F2F7','#FFF5F5F7')) { $item.Background = $inputBlue; $item.BorderBrush = [System.Windows.Media.Brushes]::Transparent; $item.BorderThickness = [System.Windows.Thickness]::new(0) }
        }
        elseif ($item -is [System.Windows.Controls.TextBlock]) { $item.Foreground = $bright }
    }
    $wsInput = $Window.FindName('WorkspaceBox')
    $searchInput = $Window.FindName('SearchBox')
    foreach ($input in @($wsInput,$searchInput)) {
        if ($input) { $input.Background = $inputBlue; $input.Foreground = $bright; $input.BorderBrush = [System.Windows.Media.Brushes]::Transparent; $input.BorderThickness = [System.Windows.Thickness]::new(0); [System.Windows.Documents.TextElement]::SetForeground($input, $bright) }
    }
    $logPanel = $Window.FindName('LogPanel')
    if ($logPanel) {
        $gradient = [System.Windows.Media.LinearGradientBrush]::new()
        $gradient.StartPoint = [System.Windows.Point]::new(0,0)
        $gradient.EndPoint = [System.Windows.Point]::new(1,1)
        [void]$gradient.GradientStops.Add([System.Windows.Media.GradientStop]::new([System.Windows.Media.ColorConverter]::ConvertFromString('#0757C9'),0.0))
        [void]$gradient.GradientStops.Add([System.Windows.Media.GradientStop]::new([System.Windows.Media.ColorConverter]::ConvertFromString('#4C1D95'),0.48))
        [void]$gradient.GradientStops.Add([System.Windows.Media.GradientStop]::new([System.Windows.Media.ColorConverter]::ConvertFromString('#0E7490'),1.0))
        $logPanel.Background = $gradient
        $logPanel.BorderBrush = [System.Windows.Media.Brushes]::Transparent
        $logPanel.BorderThickness = [System.Windows.Thickness]::new(0)
    }
    $logBox = $Window.FindName('LogBox')
    if ($logBox) {
        $logBox.Background = [System.Windows.Media.Brushes]::Transparent
        $logBox.BorderBrush = [System.Windows.Media.Brushes]::Transparent
        $logBox.BorderThickness = [System.Windows.Thickness]::new(0)
    }
    foreach ($special in @($Window.FindName('OpenWebButton'),$Window.FindName('HelpButton'),$Window.FindName('NasSettingsButton'))) { if ($special) { $special.Foreground = $cyan } }
})
foreach ($name in 'WorkspaceBox','BrowseButton','InitButton','InboxPreviewButton','InboxApplyButton','SearchBox','SearchButton','IndexButton','SnapshotPreviewButton','SnapshotButton','DoctorButton','SecurityButton','AlertsButton','ReadinessButton','RestoreButton','OpenButton','HelpButton','NasSettingsButton','OpenWebButton','LogPanel','LogBox') { Set-Variable -Name $name -Value $Window.FindName($name) }
$inputSurface = [System.Windows.Media.BrushConverter]::new().ConvertFromString('#0A2550')
$inputBorder = [System.Windows.Media.BrushConverter]::new().ConvertFromString('#3B82C4')
$inputText = [System.Windows.Media.BrushConverter]::new().ConvertFromString('#FFFFFF')
$WorkspaceBox.Background = $inputSurface
$WorkspaceBox.Foreground = $inputText
$WorkspaceBox.BorderBrush = $inputBorder
$WorkspaceBox.BorderThickness = [System.Windows.Thickness]::new(1)
$SearchBox.Background = $inputSurface
$SearchBox.Foreground = $inputText
$SearchBox.BorderBrush = $inputBorder
$SearchBox.BorderThickness = [System.Windows.Thickness]::new(1)
[System.Windows.Documents.TextElement]::SetForeground($WorkspaceBox, $inputText)
[System.Windows.Documents.TextElement]::SetForeground($SearchBox, $inputText)
$WorkspaceBox.Text = if ($Settings.workspace_path) { [string]$Settings.workspace_path } else { $WorkspacePath }

function Quote-Arg([string]$Value) {
    if($null -eq $Value){$Value=''}
    $builder = New-Object System.Text.StringBuilder
    [void]$builder.Append('"')
    $slashes = 0
    foreach($ch in $Value.ToCharArray()){
        if($ch -eq '\'){ $slashes += 1; continue }
        if($ch -eq '"'){
            if($slashes -gt 0){ [void]$builder.Append(('\' * ($slashes * 2 + 1))) } else { [void]$builder.Append('\') }
            [void]$builder.Append('"'); $slashes = 0; continue
        }
        if($slashes -gt 0){ [void]$builder.Append(('\' * $slashes)); $slashes = 0 }
        [void]$builder.Append($ch)
    }
    if($slashes -gt 0){ [void]$builder.Append(('\' * ($slashes * 2))) }
    [void]$builder.Append('"')
    $builder.ToString()
}
function Invoke-Cli([string[]]$CliArgs) {
    $psi = New-Object System.Diagnostics.ProcessStartInfo
    $psi.FileName = $PythonExecutable; $psi.Arguments = (Quote-Arg $Cli) + ' ' + (($CliArgs | ForEach-Object { Quote-Arg ([string]$_) }) -join ' ')
    $psi.WorkingDirectory = $Root; $psi.UseShellExecute = $false; $psi.CreateNoWindow = $true; $psi.RedirectStandardOutput = $true; $psi.RedirectStandardError = $true
    $proc = New-Object System.Diagnostics.Process; $proc.StartInfo = $psi; [void]$proc.Start(); $stdout = $proc.StandardOutput.ReadToEnd(); $stderr = $proc.StandardError.ReadToEnd(); $proc.WaitForExit()
    [pscustomobject]@{ ExitCode=$proc.ExitCode; Output=$stdout; Error=$stderr }
}
function Workspace-Args([string[]]$Extra) { if($Extra.Count -eq 1){return @($Extra[0],'--workspace',$WorkspaceBox.Text)}; return @($Extra[0],'--workspace',$WorkspaceBox.Text)+$Extra[1..($Extra.Count-1)] }
function Add-Log([string]$Text) { $LogBox.AppendText("[$(Get-Date -Format 'HH:mm:ss')] $Text`r`n"); $LogBox.ScrollToEnd() }
function Save-ControlCenterSettings {
    New-Item -ItemType Directory -Path $SettingsDirectory -Force | Out-Null
    [pscustomobject]@{ workspace_path = $WorkspaceBox.Text; nas_path = $script:NasPath } |
        ConvertTo-Json | Set-Content -LiteralPath $SettingsPath -Encoding utf8
}
function Run-Action([string]$Name,[string[]]$CliArgs) { try { Add-Log "开始：$Name"; $r=Invoke-Cli $CliArgs; if($r.Output.Trim()){Add-Log $r.Output.Trim()}; if($r.Error.Trim()){Add-Log ('提示：'+$r.Error.Trim())}; if($r.ExitCode -eq 0){Add-Log "完成：$Name"}else{Add-Log "失败：$Name（退出码 $($r.ExitCode)）"} } catch { Add-Log "失败：$Name · $($_.Exception.Message)" } }
function Search-Workspace {
    $query = $SearchBox.Text.Trim()
    if([string]::IsNullOrWhiteSpace($query) -or $query -eq '输入要搜索的关键词'){ Add-Log '请先输入搜索关键词'; return }
    try {
        Add-Log "正在搜索：$query"
        $result = Invoke-Cli @('search',$query,'--database',(Join-Path $WorkspaceBox.Text '08_Indexes\workspace-search.db'),'--limit','50')
        if($result.ExitCode -ne 0){ Add-Log ('搜索失败：'+$result.Error.Trim()); [System.Windows.MessageBox]::Show('搜索没有成功执行，请先点击“更新搜索索引”，再重试。','Workspace OS 搜索','OK','Warning') | Out-Null; return }
        $data = $result.Output | ConvertFrom-Json
        $rows = @($data.results)
        if($rows.Count -eq 0){ Add-Log "没有找到 [$query]"; [System.Windows.MessageBox]::Show("没有找到与 [$query] 相关的文件。",'Workspace OS 搜索','OK','Information') | Out-Null; return }
        $preview = ($rows | Select-Object -First 12 | ForEach-Object { "• $($_.name)   —   $($_.path)" }) -join "`r`n"
        Add-Log "搜索完成：找到 $($rows.Count) 个结果"
        [System.Windows.MessageBox]::Show("找到 $($rows.Count) 个结果：`r`n`r`n$preview",'Workspace OS 搜索结果','OK','Information') | Out-Null
    } catch { Add-Log "搜索失败：$($_.Exception.Message)" }
}
function Stop-WorkspaceDashboardServers {
    try {
        $servers = @(Get-CimInstance Win32_Process | Where-Object { $_.Name -like 'python*' -and $_.CommandLine -like '*dashboard_sync_server.py*' })
        foreach($server in $servers){ Stop-Process -Id $server.ProcessId -Force -ErrorAction SilentlyContinue }
        if($servers.Count -gt 0){ Add-Log "已关闭 $($servers.Count) 个旧版网页版后台服务" }
    } catch {
        Add-Log "旧版网页版服务清理失败：$($_.Exception.Message)"
    }
}
function Open-WebDashboard {
    # Always render the page with the template shipped in this portable package.
    # The old implementation opened Workspace\08_Indexes\file-locations.html
    # directly, which meant a copied package could silently show an older page
    # left on the destination computer (or on NAS).  Keep generated data in a
    # per-user temp folder so the package remains self-contained and portable.
    $workspaceRoot = [IO.Path]::GetFullPath($WorkspaceBox.Text)
    $dashboardDirectory = Join-Path $env:TEMP 'WorkspaceOS\Dashboard'
    New-Item -ItemType Directory -Path $dashboardDirectory -Force | Out-Null
    $dashboard = Join-Path $dashboardDirectory 'file-locations.html'
    $alertsPath = Join-Path $workspaceRoot '08_Indexes\Alerts\control-plane.json'
    $alertRefresh = Invoke-Cli @('alerts','--workspace',$workspaceRoot,'--output',$alertsPath)
    if($alertRefresh.ExitCode -ne 0){ Add-Log '系统状态刷新未完成；文件对比仍可正常使用。' }
    # Refresh capacity independently from the file metadata cache. This keeps
    # the fast cached comparison while preventing a missing cache from being
    # rendered as “NAS unavailable” when the SMB root is actually reachable.
    $dashboardArgs = @('locations','--computer',$workspaceRoot,'--nas',$script:NasPath,'--output',$dashboard,'--refresh-nas-capacity')
    Add-Log '正在生成并打开便携包内置的最新网页版看板…'
    try {
        $render = Invoke-Cli $dashboardArgs
        if ($render.Output.Trim()) { Add-Log $render.Output.Trim() }
        if ($render.Error.Trim()) { Add-Log ('提示：'+$render.Error.Trim()) }
        if ($render.ExitCode -ne 0 -or -not (Test-Path -LiteralPath $dashboard -PathType Leaf)) {
            throw "网页生成失败（退出码 $($render.ExitCode)）"
        }
        Add-Log "已使用包内最新版网页模板：$dashboard"
    } catch {
        Add-Log '容量刷新失败，正在使用同一包模板重试网页生成…'
        $retryArgs = @('locations','--computer',$workspaceRoot,'--nas',$script:NasPath,'--output',$dashboard)
        $retry = Invoke-Cli $retryArgs
        if ($retry.Output.Trim()) { Add-Log $retry.Output.Trim() }
        if ($retry.Error.Trim()) { Add-Log ('提示：'+$retry.Error.Trim()) }
        if ($retry.ExitCode -ne 0 -or -not (Test-Path -LiteralPath $dashboard -PathType Leaf)) {
            Add-Log "最新网页生成失败，未打开旧版工作区页面：$($_.Exception.Message)"
            return
        }
        Add-Log "已使用包内最新版网页模板（容量暂未刷新）：$dashboard"
    }
    try {
        Stop-WorkspaceDashboardServers
        $listener=[System.Net.Sockets.TcpListener]::new([System.Net.IPAddress]::Loopback,0);$listener.Start();$port=([System.Net.IPEndPoint]$listener.LocalEndpoint).Port;$listener.Stop()
        $server=Join-Path $Root 'scripts\python\dashboard_sync_server.py'
        $psi=New-Object System.Diagnostics.ProcessStartInfo;$psi.FileName=$PythonExecutable;$psi.Arguments=(Quote-Arg $server)+' --computer '+(Quote-Arg $WorkspaceBox.Text)+' --nas '+(Quote-Arg $script:NasPath)+' --dashboard '+(Quote-Arg $dashboard)+' --port '+$port;$psi.WorkingDirectory=$Root;$psi.UseShellExecute=$false;$psi.CreateNoWindow=$true
        $proc=New-Object System.Diagnostics.Process;$proc.StartInfo=$psi;[void]$proc.Start();$script:DashboardServerProcess=$proc
        $url="http://127.0.0.1:$port/dashboard#compare";$healthUrl="http://127.0.0.1:$port/api/health";for($i=0;$i -lt 10;$i++){Start-Sleep -Milliseconds 100;try{if((Invoke-WebRequest -UseBasicParsing -Uri $healthUrl -TimeoutSec 1).StatusCode -eq 200){Start-Process $url;Add-Log '网页版已启用左右对比和 Windows 高速复制：普通同步不删除，覆盖模式需二次确认';return}}catch{}}
        Add-Log '同步服务启动超时，已改为打开本地只读看板';Start-Process $dashboard
    } catch { Add-Log "同步服务不可用，打开本地只读看板：$($_.Exception.Message)";Start-Process $dashboard }
}

$BrowseButton.Add_Click({ $d=New-Object System.Windows.Forms.FolderBrowserDialog; $d.Description='选择 Workspace OS 工作区目录'; $d.SelectedPath=$WorkspaceBox.Text; if($d.ShowDialog() -eq 'OK'){$WorkspaceBox.Text=$d.SelectedPath;Save-ControlCenterSettings} })
$InitButton.Add_Click({Run-Action '初始化工作区' @('init','--path',$WorkspaceBox.Text)})
$InboxPreviewButton.Add_Click({Run-Action '扫描收件箱（预览）' (Workspace-Args @('scan-inbox'))})
$InboxApplyButton.Add_Click({Run-Action '执行收件箱整理' (Workspace-Args @('scan-inbox','--apply'))})
$IndexButton.Add_Click({Run-Action '更新搜索索引' (Workspace-Args @('search-maintain','--database',(Join-Path $WorkspaceBox.Text '08_Indexes\workspace-search.db'),'--content','--output',(Join-Path $WorkspaceBox.Text '08_Indexes\search-maintain.json')))})
$SnapshotPreviewButton.Add_Click({Run-Action '快照预览' (Workspace-Args @('snapshot','--destination',(Join-Path (Split-Path $WorkspaceBox.Text) 'WorkspaceSnapshots'),'--exclude-rebuildable-cache'))})
$SnapshotButton.Add_Click({Run-Action '创建快照' (Workspace-Args @('snapshot','--destination',(Join-Path (Split-Path $WorkspaceBox.Text) 'WorkspaceSnapshots'),'--exclude-rebuildable-cache','--apply'))})
$DoctorButton.Add_Click({Run-Action '系统健康检查' (Workspace-Args @('doctor'))})
$SecurityButton.Add_Click({Run-Action '安全检查' (Workspace-Args @('security-audit'))})
$AlertsButton.Add_Click({Run-Action '提醒与告警' (Workspace-Args @('alerts'))})
$ReadinessButton.Add_Click({Run-Action '恢复状态' (Workspace-Args @('recovery-readiness','--snapshots',(Join-Path (Split-Path $WorkspaceBox.Text) 'WorkspaceSnapshots'),'--output',(Join-Path $WorkspaceBox.Text '08_Indexes\recovery-readiness.json')))})
$RestoreButton.Add_Click({$s=New-Object System.Windows.Forms.FolderBrowserDialog;$s.Description='选择要恢复的快照目录';$s.SelectedPath=Join-Path (Split-Path $WorkspaceBox.Text) 'WorkspaceSnapshots';if($s.ShowDialog() -ne 'OK'){return};$d=New-Object System.Windows.Forms.FolderBrowserDialog;$d.Description='选择恢复目标目录（建议为新目录）';$d.SelectedPath=Join-Path (Split-Path $WorkspaceBox.Text) 'WorkspaceRestoreTests\ManualRestore';if($d.ShowDialog() -ne 'OK'){return};Run-Action '恢复快照' @('restore',$s.SelectedPath,'--destination',$d.SelectedPath,'--apply')})
$OpenButton.Add_Click({if(Test-Path -LiteralPath $WorkspaceBox.Text){Start-Process explorer.exe $WorkspaceBox.Text}else{Add-Log '工作区目录不存在，请先初始化或选择目录'}})
$HelpButton.Add_Click({Start-Process (Join-Path $Root 'docs\使用说明与功能介绍.md')})
$NasSettingsButton.Add_Click({$value=[Microsoft.VisualBasic.Interaction]::InputBox('输入 NAS 共享路径，例如 \\192.168.100.110\Workspace 或 W:\','Workspace OS · NAS 设置',$script:NasPath);if (-not [string]::IsNullOrWhiteSpace($value)) {$script:NasPath=$value.Trim();Save-ControlCenterSettings;Add-Log "NAS 路径已保存：$script:NasPath"}})
$OpenWebButton.Add_Click({Open-WebDashboard})
$SearchBox.Add_GotFocus({if($SearchBox.Text -eq '输入要搜索的关键词'){$SearchBox.Text='';$SearchBox.Foreground='#FFFFFF';[System.Windows.Documents.TextElement]::SetForeground($SearchBox,([System.Windows.Media.BrushConverter]::new().ConvertFromString('#FFFFFF')))}})
$SearchButton.Add_Click({Search-Workspace})
$SearchBox.Add_KeyDown({if($_.Key -eq 'Return'){Search-Workspace}})
Add-Log '控制中心已准备就绪。'
if ($script:NasAutoDetected) { Add-Log "配置的 NAS 路径不可访问：$script:NasConfiguredPath；已自动回退到可用入口：$script:NasPath（可在“NAS 设置”中保存新地址）" }
[void]$Window.Add_Closing({
    try {
        if ($script:DashboardServerProcess -and -not $script:DashboardServerProcess.HasExited) {
            Add-Log '正在关闭网页版后台服务…'
            $script:DashboardServerProcess.CloseMainWindow() | Out-Null
            if (-not $script:DashboardServerProcess.WaitForExit(1500)) {
                $script:DashboardServerProcess.Kill()
            }
        }
    } catch { }
})
[void]$Window.ShowDialog()
