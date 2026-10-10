using System.Windows;
namespace WorkspaceOS.IntegratedHost;
public partial class App : Application {
 System.Threading.Mutex? instance;
 protected override void OnStartup(StartupEventArgs e){
  instance=new System.Threading.Mutex(true,"Local\\WorkspaceOS.IntegratedHost",out bool created);
  if(!created){MessageBox.Show("Workspace OS 已在运行，请从任务栏打开。","Workspace OS");Shutdown();return;}
  base.OnStartup(e);
 }
 protected override void OnExit(ExitEventArgs e){instance?.Dispose();base.OnExit(e);}
}
