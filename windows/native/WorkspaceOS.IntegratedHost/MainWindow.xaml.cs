using System.Diagnostics;
using System.IO;
using System.Net.Http;
using System.Text.Json.Nodes;
using System.Text;
using System.Windows;
using System.Windows.Controls;
using System.Windows.Media;
using Microsoft.Web.WebView2.Core;
using Microsoft.Win32;
namespace WorkspaceOS.IntegratedHost;
public partial class MainWindow : Window {
 readonly string root=AppContext.BaseDirectory;
 readonly string data=Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData),"WorkspaceOS","Integrated");
 readonly string settings=Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.ApplicationData),"WorkspaceOS","control-center-settings.json");
 readonly HttpClient http=new(){Timeout=TimeSpan.FromSeconds(3)};
 readonly TextBox workspace=new(), nas=new(), log=new(){IsReadOnly=true,Height=210,TextWrapping=TextWrapping.Wrap,VerticalScrollBarVisibility=ScrollBarVisibility.Auto};
 readonly StackPanel controls=new(){Margin=new Thickness(24)};
 ScrollViewer panel=new(); Process? server; string? origin; bool busy,checkingClose,allowClose;
 readonly System.Windows.Threading.DispatcherTimer heartbeat=new(){Interval=TimeSpan.FromSeconds(5)};
 public MainWindow(){
  InitializeComponent();Directory.CreateDirectory(data);BuildControls();
  var icon=Path.Combine(root,"WorkspaceOS-NEXUS.ico");if(File.Exists(icon))Icon=System.Windows.Media.Imaging.BitmapFrame.Create(new Uri(icon));
  Loaded+=async(_,_)=>{if(Directory.Exists(workspace.Text)&&nas.Text.Length>0)await StartAsync();};
  heartbeat.Tick+=async(_,_)=>{if(origin!=null)try{await http.GetAsync(origin+"/api/health");}catch{StatusText.Text="连接已断开，请重新连接";}};
  Closing+=async(_,e)=>{if(allowClose)return;e.Cancel=true;if(checkingClose)return;checkingClose=true;
   try{if(busy||await Transferring()){MessageBox.Show(this,"请等待当前操作和文件传输完成后再退出。","Workspace OS");return;}
    StopServer();Browser.Dispose();allowClose=true;Close();
   }catch(Exception ex){Log(ex.Message);}finally{checkingClose=false;}};
 }
 void BuildControls(){
  var grid=(Grid)Content;var layout=new Grid();layout.RowDefinitions.Add(new RowDefinition{Height=GridLength.Auto});layout.RowDefinitions.Add(new RowDefinition());
  grid.Children.Remove(Browser);Grid.SetRow(layout,1);grid.Children.Add(layout);
  var side=new StackPanel{Orientation=Orientation.Horizontal,Margin=new Thickness(20,10,20,2)};layout.Children.Add(side);
  Button Nav(string label,Action action){var b=Button(label);b.Click+=(_,_)=>action();side.Children.Add(b);return b;}
  Nav("文件与 NAS",()=>{if(origin!=null){panel.Visibility=Visibility.Collapsed;Browser.Visibility=Visibility.Visible;}else Log("请先配置工作区与 NAS。");});
  Nav("控制中心",()=>{Browser.Visibility=Visibility.Collapsed;panel.Visibility=Visibility.Visible;});
  side.Children.Add(new TextBlock{Text="2.2.0  ·  新结构 / 本地优先 / 按需备份",Foreground=Brushes.LightSteelBlue,VerticalAlignment=VerticalAlignment.Center,Margin=new Thickness(16,0,0,8)});
  var area=new Grid();Grid.SetRow(area,1);layout.Children.Add(area);Grid.SetRow(Browser,0);area.Children.Add(Browser);
  controls.MaxWidth=1120;controls.HorizontalAlignment=HorizontalAlignment.Stretch;
  panel=new ScrollViewer{Content=controls,VerticalScrollBarVisibility=ScrollBarVisibility.Auto,Background=new LinearGradientBrush(Color.FromRgb(13,24,48),Color.FromRgb(20,39,66),35)};area.Children.Add(panel);
  controls.Children.Add(new TextBlock{Text="控制中心",FontSize=26,FontWeight=FontWeights.SemiBold,Foreground=Brushes.AliceBlue});
  controls.Children.Add(new TextBlock{Text="管理连接、维护工作区，查看每一次操作的结果。",FontSize=13,Foreground=Brushes.LightSteelBlue,Margin=new Thickness(0,6,0,20)});
  var columns=new Grid();columns.ColumnDefinitions.Add(new ColumnDefinition());columns.ColumnDefinitions.Add(new ColumnDefinition());controls.Children.Add(columns);
  StackPanel Card(string title,Panel parent,int column=0){var body=new StackPanel();var card=new Border{CornerRadius=new CornerRadius(18),Padding=new Thickness(20),Margin=new Thickness(0,0,column==0?12:0,12),Background=new SolidColorBrush(Color.FromArgb(175,19,36,61)),Child=body};Grid.SetColumn(card,column);parent.Children.Add(card);body.Children.Add(new TextBlock{Text=title,FontSize=16,FontWeight=FontWeights.SemiBold,Foreground=Brushes.AliceBlue,Margin=new Thickness(0,0,0,14)});return body;}
  var connection=Card("工作区连接",columns);var maintenance=Card("维护与恢复",columns,1);
  void Label(string text)=>connection.Children.Add(new TextBlock{Text=text,Foreground=Brushes.LightSteelBlue,FontSize=12,Margin=new Thickness(0,8,0,6)});
  Label("电脑工作区");
  foreach(var box in new[]{workspace,nas,log}){box.Background=new SolidColorBrush(Color.FromRgb(18,42,70));box.Foreground=Brushes.AliceBlue;box.CaretBrush=Brushes.Cyan;box.Padding=new Thickness(10);box.BorderThickness=new Thickness(0);box.Margin=new Thickness(0,4,0,8);}
  workspace.Text=Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.MyDocuments),"Workspace");
  try{if(File.Exists(settings)){var o=JsonNode.Parse(File.ReadAllText(settings));workspace.Text=(string?)o?["workspace_path"]??workspace.Text;nas.Text=(string?)o?["nas_path"]??"";}}catch(Exception ex){Log(ex.Message);}
  var pathRow=new Grid();pathRow.ColumnDefinitions.Add(new ColumnDefinition());pathRow.ColumnDefinitions.Add(new ColumnDefinition{Width=new GridLength(104)});connection.Children.Add(pathRow);
  pathRow.Children.Add(workspace);workspace.Margin=new Thickness(0,0,8,10);workspace.Height=42;
  var choose=Button("浏览目录");choose.Click+=(_,_)=>{var d=new OpenFolderDialog();if(d.ShowDialog(this)==true)workspace.Text=d.FolderName;};Grid.SetColumn(choose,1);pathRow.Children.Add(choose);
  Label("NAS 共享路径或映射盘");connection.Children.Add(nas);
  nas.Height=42;
  var connectActions=new System.Windows.Controls.Primitives.UniformGrid{Columns=2,Margin=new Thickness(-4,6,-4,0)};connection.Children.Add(connectActions);
  var test=Button("测试连接");test.Click+=async(_,_)=>await TestConnection(test);connectActions.Children.Add(test);
  var reconnect=Button("重新连接");reconnect.Click+=async(_,_)=>await StartAsync();connectActions.Children.Add(reconnect);
  var save=Button("保存并打开工作台");save.Click+=async(_,_)=>{if(busy)return;try{if(await Transferring())throw new Exception("请先等待传输完成。");var o=File.Exists(settings)?JsonNode.Parse(File.ReadAllText(settings)) as JsonObject:new JsonObject();o??=new();o["workspace_path"]=Path.GetFullPath(workspace.Text);o["nas_path"]=nas.Text.Trim();Directory.CreateDirectory(Path.GetDirectoryName(settings)!);File.WriteAllText(settings,o.ToJsonString());await StartAsync();}catch(Exception ex){Log(ex.Message);}};controls.Children.Add(save);
  controls.Children.Remove(save);connection.Children.Add(save);save.Background=new LinearGradientBrush(Color.FromRgb(90,74,210),Color.FromRgb(43,103,200),0);
  System.Windows.Controls.Primitives.UniformGrid Group(string title,StackPanel parent,int count=2){parent.Children.Add(new TextBlock{Text=title,FontSize=11,Foreground=Brushes.LightSteelBlue,Margin=new Thickness(0,8,0,8)});var g=new System.Windows.Controls.Primitives.UniformGrid{Columns=count,Margin=new Thickness(-4,0,-4,4)};parent.Children.Add(g);return g;}
  var daily=Group("日常管理",maintenance);var recovery=Group("备份与恢复 · 仅手动执行",maintenance);var checks=Group("健康与安全",maintenance,3);var actions=Group("快捷入口",connection,3);
  var commands=new Dictionary<string,string>{{"初始化工作区","init"},{"收件箱预览","inbox"},{"执行收件箱整理","inbox-apply"},{"更新搜索索引","index"},{"快照预览","snapshot"},{"手动创建快照","snapshot-apply"},{"系统健康检查","doctor"},{"安全检查","security-audit"},{"提醒与告警","alerts"},{"恢复状态","recovery-readiness"},{"恢复到新目录","restore"}};
  foreach(var pair in commands){var b=Button(pair.Key);b.Click+=async(_,_)=>await RunAction(pair.Key,pair.Value);var target=pair.Value is "doctor" or "security-audit" or "alerts"?checks:pair.Value is "snapshot" or "snapshot-apply" or "restore" or "recovery-readiness"?recovery:daily;target.Children.Add(b);}
  foreach(var pair in new[]{("打开本地目录",false),("打开 NAS 目录",true)}){var b=Button(pair.Item1);b.Click+=(_,_)=>{try{var psi=new ProcessStartInfo("explorer.exe"){UseShellExecute=true};psi.ArgumentList.Add(pair.Item2?nas.Text:workspace.Text);Process.Start(psi);}catch(Exception ex){Log(ex.Message);}};actions.Children.Add(b);}
  var help=Button("使用说明");help.Click+=(_,_)=>Log("选择电脑工作区并填写 NAS 路径，保存后进入工作台。文件查找、筛选、左右对比、上传下载和覆盖均在工作台。覆盖前会确认；快照仅手动创建。传输完成后再退出。");actions.Children.Add(help);
  var activity=Card("活动日志",controls,1);log.Height=165;log.FontFamily=new FontFamily("Consolas");log.FontSize=12;activity.Children.Add(log);
 }
 async Task TestConnection(Button button){
  if(busy)return;var path=nas.Text.Trim();if(string.IsNullOrEmpty(path)){Log("请先填写 NAS 路径。");return;}
  button.IsEnabled=false;button.Content="正在测试…";
  try{var psi=new ProcessStartInfo(Path.Combine(root,"runtime","python","python.exe")){UseShellExecute=false,CreateNoWindow=true,RedirectStandardOutput=true,RedirectStandardError=true};psi.ArgumentList.Add("-c");psi.ArgumentList.Add("import os,sys; sys.exit(0 if os.path.isdir(sys.argv[1]) else 1)");psi.ArgumentList.Add(path);using var probe=Process.Start(psi)??throw new Exception("无法启动连接测试");using var timeout=new CancellationTokenSource(TimeSpan.FromSeconds(8));try{await probe.WaitForExitAsync(timeout.Token);}catch(OperationCanceledException){probe.Kill(true);throw new Exception("连接超时，请检查网络或 NAS 登录状态。");}Log(probe.ExitCode==0?"NAS 连接成功：共享目录可以访问（未写入文件）。":"NAS 目录无法访问，请先在资源管理器登录后重试。");}
  catch(Exception ex){Log(ex.Message);}finally{button.Content="测试连接";button.IsEnabled=true;}
 }
 static Button Button(string title){var b=new Button{Content=title,HorizontalAlignment=HorizontalAlignment.Stretch,Height=40,MinWidth=0,FontSize=12,Foreground=Brushes.AliceBlue,Background=new SolidColorBrush(Color.FromRgb(31,49,77)),Margin=new Thickness(4,0,4,8),Cursor=System.Windows.Input.Cursors.Hand,ToolTip=title};
  var border=new FrameworkElementFactory(typeof(Border));border.SetValue(Border.CornerRadiusProperty,new CornerRadius(10));border.SetBinding(Border.BackgroundProperty,new System.Windows.Data.Binding("Background"){RelativeSource=new(System.Windows.Data.RelativeSourceMode.TemplatedParent)});border.SetValue(Border.PaddingProperty,new Thickness(12,0,12,0));var presenter=new FrameworkElementFactory(typeof(ContentPresenter));presenter.SetValue(HorizontalAlignmentProperty,HorizontalAlignment.Center);presenter.SetValue(VerticalAlignmentProperty,VerticalAlignment.Center);border.AppendChild(presenter);var template=new ControlTemplate(typeof(Button)){VisualTree=border};var hover=new Trigger{Property=IsMouseOverProperty,Value=true};hover.Setters.Add(new Setter(OpacityProperty,0.8));template.Triggers.Add(hover);var disabled=new Trigger{Property=IsEnabledProperty,Value=false};disabled.Setters.Add(new Setter(OpacityProperty,0.45));template.Triggers.Add(disabled);b.Template=template;return b;}
 void Log(string message){StatusText.Text=message.Split('\n')[0];log.AppendText($"[{DateTime.Now:HH:mm:ss}] {message}\n");log.ScrollToEnd();}
 Process Launch(string script,IEnumerable<string> args,bool capture=true){var psi=new ProcessStartInfo(Path.Combine(root,"runtime","python","python.exe")){UseShellExecute=false,CreateNoWindow=true,WorkingDirectory=root,RedirectStandardOutput=capture,RedirectStandardError=capture};if(capture){psi.StandardOutputEncoding=Encoding.UTF8;psi.StandardErrorEncoding=Encoding.UTF8;}psi.Environment["PYTHONIOENCODING"]="utf-8";psi.Environment["PYTHONUTF8"]="1";psi.ArgumentList.Add(Path.Combine(root,"scripts","python",script));foreach(var a in args)psi.ArgumentList.Add(a);return Process.Start(psi)??throw new Exception("启动核心服务失败");}
 async Task<string> Execute(params string[] args){using var p=Launch("workspace_cli.py",args);var output=p.StandardOutput.ReadToEndAsync();var error=p.StandardError.ReadToEndAsync();await p.WaitForExitAsync();var text=await output;var stderr=await error;if(text.Length>0&&args[0] is not ("doctor" or "security-audit" or "alerts"))Log(text.Length>16000?text[^16000..]:text);if(p.ExitCode!=0)throw new Exception($"操作失败（{p.ExitCode}）：{stderr}\n{text}");if(!string.IsNullOrWhiteSpace(stderr))Log(stderr);return text;}
 void ShowCheckResult(string title,string key,string text){
  var report=JsonNode.Parse(text);var items=(report?["findings"]??report?["alerts"]) as JsonArray??new JsonArray();
  var description=key switch{"doctor"=>"检查工作区目录、磁盘空间、缓存及备份状态。本按钮未检测 NAS；NAS 请使用测试连接。","security-audit"=>"检查疑似明文凭据和越界链接等风险；不是杀毒软件，不会自动删除或修复文件。",_=>"汇总已有健康、审计、备份与索引报告；不是重新扫描，旧报告可能产生过期提醒。"};
  var lines=new StringBuilder(description+"\n\n检查已完成；执行成功不代表没有风险。\n");
  foreach(var severity in new[]{"CRITICAL","ERROR","WARNING","INFO"}){var count=items.Count(x=>(string?)x?["severity"]==severity);var label=severity switch{"CRITICAL"=>"严重","ERROR"=>"错误","WARNING"=>"提醒",_=>"信息"};lines.AppendLine($"{label}：{count}");}
  if(items.Count==0)lines.AppendLine("当前检查范围内未发现问题。");
  foreach(var item in items)lines.AppendLine($"\n[{item?["severity"]}] {item?["message"]}\n{item?["path"]}");
  var outputs=(report?["outputs"]??report?["reports"]) as JsonArray;if(outputs!=null){lines.AppendLine("\n报告保存位置：");foreach(var output in outputs)lines.AppendLine(output?.ToString());}
  Log(title+"：发现 "+items.Count+" 项，详情见检查结果窗口。" );
  var box=new TextBox{Text=lines.ToString(),IsReadOnly=true,TextWrapping=TextWrapping.Wrap,VerticalScrollBarVisibility=ScrollBarVisibility.Auto,Padding=new Thickness(20),BorderThickness=new Thickness(0),Background=new SolidColorBrush(Color.FromRgb(15,29,49)),Foreground=Brushes.AliceBlue,FontFamily=new FontFamily("Microsoft YaHei UI"),FontSize=14};
  new Window{Title=title+" · 检查结果",Owner=this,Width=760,Height=560,WindowStartupLocation=WindowStartupLocation.CenterOwner,Content=box}.ShowDialog();
 }
 async Task<bool> Transferring(){if(server==null||server.HasExited||origin==null)return false;var o=JsonNode.Parse(await http.GetStringAsync(origin+"/api/sync/jobs"));return o?["jobs"]?.AsArray().Any(j=>new[]{"queued","scanning","running"}.Contains((string?)j?["status"]))==true;}
 void StopServer(){heartbeat.Stop();try{if(server!=null&&!server.HasExited){server.Kill(true);server.WaitForExit(3000);}}finally{server?.Dispose();server=null;origin=null;}}
 async Task StartAsync(){if(busy)return;busy=true;try{
  if(await Transferring())throw new Exception("请等待传输完成后重新连接。");
  if(!Directory.Exists(workspace.Text))throw new Exception("请先选择或初始化电脑工作区。");if(string.IsNullOrWhiteSpace(nas.Text))throw new Exception("请填写 NAS 路径。");
  StopServer();Log("正在准备工作台…");var dash=Path.Combine(data,"file-locations.html");
  await Execute("locations","--computer",workspace.Text,"--nas",nas.Text,"--output",dash);
  var l=new System.Net.Sockets.TcpListener(System.Net.IPAddress.Loopback,0);l.Start();var port=((System.Net.IPEndPoint)l.LocalEndpoint).Port;l.Stop();
  server=Launch("dashboard_sync_server.py",new[]{"--computer",workspace.Text,"--nas",nas.Text,"--dashboard",dash,"--port",port.ToString()},false);
  origin=$"http://127.0.0.1:{port}";bool ready=false;
  for(int i=0;i<40;i++){if(server.HasExited)throw new Exception("同步服务已退出。");try{ready=(await http.GetAsync(origin+"/api/health")).IsSuccessStatusCode;}catch{}if(ready)break;await Task.Delay(100);}
  if(!ready)throw new Exception("同步服务启动超时。");
  if(Browser.CoreWebView2==null){var env=await CoreWebView2Environment.CreateAsync(null,Path.Combine(data,"WebView2"));await Browser.EnsureCoreWebView2Async(env);
   Browser.CoreWebView2.NavigationStarting+=(_,e)=>{if(e.Uri!= "about:blank"&&!e.Uri.StartsWith(origin+"/",StringComparison.Ordinal))e.Cancel=true;};
   Browser.CoreWebView2.NewWindowRequested+=(_,e)=>{e.Handled=true;Log("请使用页面中的打开目录按钮。");};Browser.CoreWebView2.Settings.IsStatusBarEnabled=false;}
  Browser.Source=new Uri(origin+"/dashboard");heartbeat.Start();panel.Visibility=Visibility.Collapsed;Browser.Visibility=Visibility.Visible;Log("工作台已连接");
 }catch(Exception ex){Log(ex.Message);Browser.Visibility=Visibility.Collapsed;panel.Visibility=Visibility.Visible;}finally{busy=false;}}
 async Task RunAction(string title,string key){if(busy)return;busy=true;try{if(await Transferring())throw new Exception("请先等待文件传输完成。");if(key.EndsWith("-apply")&&MessageBox.Show(this,"确认执行："+title+"？","Workspace OS",MessageBoxButton.YesNo)!=MessageBoxResult.Yes)return;
 string w=workspace.Text,s=Path.Combine(Path.GetDirectoryName(Path.GetFullPath(w))!,"WorkspaceSnapshots");
  string indexes=Path.Combine(w,"09_System","RuntimeLogs","WorkspaceOS","Indexes");
  string[] a=key switch{
   "init"=>new[]{"init","--path",w},
   "doctor"=>new[]{"doctor","--workspace",w,"--output",Path.Combine(indexes,"Health","workspace-health.json")},
   "inbox"=>new[]{"scan-inbox","--workspace",w},
   "inbox-apply"=>new[]{"scan-inbox","--workspace",w,"--apply"},
   "index"=>new[]{"search-maintain","--workspace",w,"--database",Path.Combine(indexes,"Search","workspace-search.db"),"--content"},
   "snapshot"=>new[]{"snapshot","--workspace",w,"--destination",s,"--exclude-rebuildable-cache"},
   "snapshot-apply"=>new[]{"snapshot","--workspace",w,"--destination",s,"--exclude-rebuildable-cache","--apply"},
   "recovery-readiness"=>new[]{key,"--workspace",w,"--snapshots",s},
   _=>new[]{key,"--workspace",w}};
  if(key=="restore"){var d=new OpenFolderDialog{Title="选择快照目录"};if(d.ShowDialog(this)!=true)return;var t=new SaveFileDialog{Title="指定尚不存在的恢复目录",FileName="Workspace-Restored",CheckFileExists=false};if(t.ShowDialog(this)!=true)return;a=new[]{"restore",d.FolderName,"--destination",t.FileName,"--apply"};}
  Log("正在执行："+title);var result=await Execute(a);Log(title+"完成");if(key is "doctor" or "security-audit" or "alerts")ShowCheckResult(title,key,result);
 }catch(Exception ex){Log(ex.Message);}finally{busy=false;}}
}
