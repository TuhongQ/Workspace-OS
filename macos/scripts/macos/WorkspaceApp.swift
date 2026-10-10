import AppKit
import WebKit

// Native, single-window host. The Python runtime is bundled; no system Python
// or browser extension is required on the installed Mac.
final class WorkspaceApp: NSObject, NSApplicationDelegate, WKNavigationDelegate, WKUIDelegate, WKDownloadDelegate {
    var window: NSWindow!
    var web: WKWebView!
    var backend: Process?
    var readyTimer: Timer?
    var baseURL: URL?
    var launchTime = Date()
    var generation = UUID()
    let fm = FileManager.default
    let settingsURL = FileManager.default.homeDirectoryForCurrentUser.appendingPathComponent("Library/Application Support/WorkspaceOS/control-center-settings.json")
    var settings: [String: String] = [:]
    var status = NSTextField(labelWithString: "正在启动…")
    var logHandle: FileHandle?
    var maintenance: Process?
    var computer: String { settings["workspace_path"] ?? fm.homeDirectoryForCurrentUser.appendingPathComponent("Workspace").path }
    var nas: String { settings["nas_path"] ?? "/Volumes/Workspace" }
    var root: URL { Bundle.main.resourceURL!.appendingPathComponent("WorkspaceOS") }

    func applicationDidFinishLaunching(_ notification: Notification) {
        NSApp.appearance = NSAppearance(named: .darkAqua)
        if let data = try? Data(contentsOf: settingsURL),
           let saved = try? JSONDecoder().decode([String: String].self, from: data) { settings = saved }
        let main = NSMenu()
        let appItem = NSMenuItem(); main.addItem(appItem)
        let appMenu = NSMenu(); appItem.submenu = appMenu
        appMenu.addItem(withTitle: "关于 Workspace OS", action: #selector(about), keyEquivalent: "")
        appMenu.addItem(withTitle: "设置…", action: #selector(preferences), keyEquivalent: ",")
        appMenu.addItem(.separator())
        appMenu.addItem(withTitle: "退出 Workspace OS", action: #selector(NSApplication.terminate(_:)), keyEquivalent: "q")
        let editItem = NSMenuItem(); main.addItem(editItem)
        let edit = NSMenu(title: "编辑"); editItem.submenu = edit
        edit.addItem(withTitle: "剪切", action: #selector(NSText.cut(_:)), keyEquivalent: "x")
        edit.addItem(withTitle: "复制", action: #selector(NSText.copy(_:)), keyEquivalent: "c")
        edit.addItem(withTitle: "粘贴", action: #selector(NSText.paste(_:)), keyEquivalent: "v")
        edit.addItem(withTitle: "全选", action: #selector(NSText.selectAll(_:)), keyEquivalent: "a")
        let toolsItem = NSMenuItem(); main.addItem(toolsItem)
        let toolsMenu = NSMenu(title: "Workspace"); toolsItem.submenu = toolsMenu
        toolsMenu.addItem(withTitle: "更新 NEXUS", action: #selector(refresh), keyEquivalent: "r")
        toolsMenu.addItem(withTitle: "连接 NAS（SMB）", action: #selector(connectNAS), keyEquivalent: "k")
        toolsMenu.addItem(withTitle: "QuickConnect 网页访问", action: #selector(quickConnect), keyEquivalent: "")
        toolsMenu.addItem(withTitle: "在浏览器中打开", action: #selector(openBrowser), keyEquivalent: "")
        toolsMenu.addItem(withTitle: "使用说明", action: #selector(help), keyEquivalent: "?")
        toolsMenu.addItem(withTitle: "高级工具（快照、搜索、恢复）", action: #selector(advanced), keyEquivalent: "")
        toolsMenu.addItem(withTitle: "查看运行日志", action: #selector(openLogs), keyEquivalent: "")
        toolsMenu.addItem(withTitle: "重新启动本地服务", action: #selector(retry), keyEquivalent: "")
        NSApp.mainMenu = main

        window = NSWindow(contentRect: NSRect(x: 0, y: 0, width: 1280, height: 850),
                          styleMask: [.titled, .closable, .miniaturizable, .resizable], backing: .buffered, defer: false)
        window.title = "Workspace OS · NEXUS"
        window.minSize = NSSize(width: 900, height: 620)
        window.isReleasedWhenClosed = false
        window.setFrameAutosaveName("WorkspaceOSNativeWindow")
        window.titlebarAppearsTransparent = true
        window.backgroundColor = .windowBackgroundColor
        let config = WKWebViewConfiguration()
        web = WKWebView(frame: .zero, configuration: config)
        web.navigationDelegate = self; web.uiDelegate = self
        web.allowsBackForwardNavigationGestures = true
        if #available(macOS 13.3, *) { web.isInspectable = true }
        let bar = NSStackView()
        bar.orientation = .horizontal; bar.spacing = 12
        for (title, selector) in [("本地文件", #selector(openLocal)), ("NAS 文件", #selector(openNAS)),
                                  ("连接 NAS", #selector(connectNAS)), ("更新 NEXUS", #selector(refresh)),
                                  ("设置", #selector(preferences))] {
            let button = NSButton(title: title, target: self, action: selector)
            button.bezelStyle = .rounded
            bar.addArrangedSubview(button)
        }
        status.font = .systemFont(ofSize: 11)
        status.textColor = .secondaryLabelColor
        status.setContentCompressionResistancePriority(.defaultLow, for: .horizontal)
        bar.addArrangedSubview(status)
        let content = NSView()
        content.addSubview(bar); content.addSubview(web)
        bar.translatesAutoresizingMaskIntoConstraints = false
        web.translatesAutoresizingMaskIntoConstraints = false
        NSLayoutConstraint.activate([
            bar.leadingAnchor.constraint(equalTo: content.leadingAnchor, constant: 16),
            bar.trailingAnchor.constraint(equalTo: content.trailingAnchor, constant: -16),
            bar.topAnchor.constraint(equalTo: content.topAnchor, constant: 8),
            bar.heightAnchor.constraint(equalToConstant: 32),
            web.topAnchor.constraint(equalTo: bar.bottomAnchor, constant: 8),
            web.leadingAnchor.constraint(equalTo: content.leadingAnchor),
            web.trailingAnchor.constraint(equalTo: content.trailingAnchor),
            web.bottomAnchor.constraint(equalTo: content.bottomAnchor)
        ])
        window.contentView = content
        window.center(); window.makeKeyAndOrderFront(nil)
        NSApp.activate(ignoringOtherApps: true)
        startBackend()
    }

    func startBackend() {
        readyTimer?.invalidate()
        backend?.terminate()
        baseURL = nil; generation = UUID()
        let currentGeneration = generation
        launchTime = Date()
        status.stringValue = "正在读取本地索引 · 不自动同步"
        let ready = fm.temporaryDirectory.appendingPathComponent("workspaceos-ready-\(UUID().uuidString).json")
        let logs = fm.homeDirectoryForCurrentUser.appendingPathComponent("Library/Logs/WorkspaceOS")
        do {
            try fm.createDirectory(at: logs, withIntermediateDirectories: true)
            let logfile = logs.appendingPathComponent("native-app.log")
            if !fm.fileExists(atPath: logfile.path) { fm.createFile(atPath: logfile.path, contents: nil) }
            logHandle = try FileHandle(forWritingTo: logfile)
            try logHandle?.seekToEnd()
            let process = Process()
            process.executableURL = Bundle.main.bundleURL.appendingPathComponent("Contents/MacOS/WorkspaceOSHelper")
            process.arguments = ["desktop", "--computer", computer, "--nas", nas, "--ready-file", ready.path,
                                 "--parent-pid", String(ProcessInfo.processInfo.processIdentifier)]
            var env = ProcessInfo.processInfo.environment
            env["WORKSPACE_OS_ROOT"] = root.path
            env["PYTHONUNBUFFERED"] = "1"
            process.environment = env
            process.standardOutput = logHandle; process.standardError = logHandle
            process.terminationHandler = { [weak self] process in
                DispatchQueue.main.async {
                    guard let self = self, self.generation == currentGeneration else { return }
                    self.readyTimer?.invalidate()
                    self.baseURL = nil
                    self.status.stringValue = "服务已停止 · 可从 Workspace 菜单重新启动"
                    if process.terminationStatus != 0 {
                        self.alert("本地服务启动失败", "未执行自动同步。请检查设置中的目录，或通过 Workspace → 查看运行日志定位原因。")
                    }
                }
            }
            backend = process
            try process.run()
            readyTimer = Timer.scheduledTimer(withTimeInterval: 0.25, repeats: true) { [weak self] timer in
                guard let self = self else { timer.invalidate(); return }
                if let data = try? Data(contentsOf: ready),
                   let payload = try? JSONSerialization.jsonObject(with: data) as? [String: Int],
                   let port = payload["port"], let url = URL(string: "http://127.0.0.1:\(port)/dashboard") {
                    timer.invalidate()
                    try? self.fm.removeItem(at: ready)
                    self.baseURL = url
                    self.web.load(URLRequest(url: url))
                    self.status.stringValue = "2.0.6 · 手动传输 · 无自动同步"
                } else if Date().timeIntervalSince(self.launchTime) > 60 {
                    timer.invalidate()
                    self.status.stringValue = "启动耗时较长 · 请查看日志或重新启动服务"
                }
            }
        } catch { alert("无法启动", error.localizedDescription) }
    }

    func requestJobs(_ completion: @escaping (Bool?) -> Void) {
        if backend?.isRunning != true { completion(false); return }
        guard let base = baseURL else { completion(false); return }
        let url = base.deletingLastPathComponent().appendingPathComponent("api/sync/jobs")
        var request = URLRequest(url: url); request.timeoutInterval = 5
        URLSession.shared.dataTask(with: request) { data, _, _ in
            let object = data.flatMap { try? JSONSerialization.jsonObject(with: $0) as? [String: Any] }
            let jobs = object?["jobs"] as? [[String: Any]]
            let active = jobs.map { $0.contains { ["queued", "scanning", "running"].contains($0["status"] as? String ?? "") } }
            DispatchQueue.main.async { completion(active) }
        }.resume()
    }

    func whenIdle(_ action: @escaping () -> Void) {
        requestJobs { [weak self] active in
            guard active == false else {
                self?.alert("暂不能更改服务", active == true ? "还有传输任务，请等待完成后再操作。" : "尚未确认任务状态。请稍后重试，避免中断传输。")
                return
            }
            action()
        }
    }
    @objc func retry() { whenIdle { self.startBackend() } }
    @objc func refresh() {
        guard baseURL != nil else { alert("服务尚未就绪", "请先等待启动完成。"); return }
        web.evaluateJavaScript("void refreshDirectories()") { [weak self] _, error in
            if let error = error { self?.alert("更新未启动", error.localizedDescription) }
        }
    }
    @objc func openLocal() { openFolder(computer) }
    @objc func openNAS() { openFolder(nas) }
    func openFolder(_ path: String) {
        var directory: ObjCBool = false
        guard fm.fileExists(atPath: path, isDirectory: &directory), directory.boolValue else {
            alert("目录不可读取", "NAS 尚未挂载时，请先点击“连接 NAS”。"); return
        }
        NSWorkspace.shared.open(URL(fileURLWithPath: path))
    }
    @objc func connectNAS() {
        let address = settings["smb_url"] ?? "smb://192.168.1.9/Workspace"
        guard let url = URL(string: address), url.scheme == "smb", url.user == nil, url.password == nil else {
            alert("SMB 地址无效", "请在设置中输入不含账号密码的 smb://主机/共享目录。"); return
        }
        NSWorkspace.shared.open(url)
    }
    @objc func quickConnect() {
        let dialog = NSAlert()
        dialog.messageText = "QuickConnect 网页访问"
        dialog.informativeText = "可重新输入 ID。QuickConnect 打开群晖网页，不等于 SMB 挂载；账号密码只在群晖页面输入。"
        dialog.addButton(withTitle: "打开"); dialog.addButton(withTitle: "取消")
        let input = NSTextField(string: settings["quickconnect_id"] ?? "")
        input.frame = NSRect(x: 0, y: 0, width: 340, height: 26)
        dialog.accessoryView = input
        guard dialog.runModal() == .alertFirstButtonReturn else { return }
        let id = input.stringValue.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !id.isEmpty, id.range(of: "^[A-Za-z0-9-]+$", options: .regularExpression) != nil,
              let url = URL(string: "https://quickconnect.to/\(id)") else {
            alert("ID 格式无效", "仅输入 QuickConnect ID，不要输入网址或密码。"); return
        }
        settings["quickconnect_id"] = id
        do { try saveSettings(); NSWorkspace.shared.open(url) }
        catch { alert("设置未保存", error.localizedDescription) }
    }
    @objc func preferences() {
        whenIdle { self.showPreferences() }
    }
    func showPreferences() {
        let dialog = NSAlert()
        dialog.messageText = "Workspace 设置"
        dialog.informativeText = "设置只保存路径和连接 ID，不保存密码。SMB 支持局域网或已配置的 VPN 地址；QuickConnect 不是挂载地址。"
        dialog.addButton(withTitle: "保存并重启服务"); dialog.addButton(withTitle: "取消")
        let rows = NSStackView(); rows.orientation = .vertical; rows.alignment = .leading; rows.spacing = 6
        var inputs: [String: NSTextField] = [:]
        for (key, title, value) in [
            ("workspace_path", "本地工作区", computer), ("nas_path", "NAS 挂载路径", nas),
            ("smb_url", "SMB 服务器", settings["smb_url"] ?? "smb://192.168.1.9/Workspace"),
            ("quickconnect_id", "QuickConnect ID", settings["quickconnect_id"] ?? "")
        ] {
            rows.addArrangedSubview(NSTextField(labelWithString: title))
            let input = NSTextField(string: value)
            input.widthAnchor.constraint(equalToConstant: 460).isActive = true
            rows.addArrangedSubview(input); inputs[key] = input
        }
        rows.frame = NSRect(x: 0, y: 0, width: 460, height: 220)
        dialog.accessoryView = rows
        guard dialog.runModal() == .alertFirstButtonReturn else { return }
        var candidate = settings
        for (key, field) in inputs { candidate[key] = field.stringValue.trimmingCharacters(in: .whitespacesAndNewlines) }
        let local = NSString(string: candidate["workspace_path"] ?? "").expandingTildeInPath
        let remote = NSString(string: candidate["nas_path"] ?? "").expandingTildeInPath
        let l = URL(fileURLWithPath: local).resolvingSymlinksInPath().path
        let n = URL(fileURLWithPath: remote).resolvingSymlinksInPath().path
        guard local.hasPrefix("/"), remote.hasPrefix("/"), l != n,
              !l.hasPrefix(n + "/"), !n.hasPrefix(l + "/"), fm.fileExists(atPath: local),
              let smb = URL(string: candidate["smb_url"] ?? ""), smb.scheme == "smb",
              smb.host != nil, smb.user == nil, smb.password == nil else {
            alert("设置未保存", "请检查绝对路径、本地目录、两端是否重叠，以及 SMB 地址是否不含账号密码。"); return
        }
        candidate["workspace_path"] = local; candidate["nas_path"] = remote
        let previous = settings; settings = candidate
        do { try saveSettings(); startBackend() } catch { settings = previous; alert("保存失败", error.localizedDescription) }
    }
    func saveSettings() throws {
        try fm.createDirectory(at: settingsURL.deletingLastPathComponent(), withIntermediateDirectories: true)
        try JSONEncoder().encode(settings).write(to: settingsURL, options: .atomic)
    }
    @objc func openBrowser() { if let url = baseURL { NSWorkspace.shared.open(url) } }
    @objc func advanced() {
        whenIdle {
            if self.maintenance?.isRunning == true {
                self.alert("高级工具已打开", "请切换到高级控制中心窗口。"); return
            }
            let process = Process()
            process.executableURL = Bundle.main.bundleURL.appendingPathComponent("Contents/MacOS/WorkspaceOSMaintenance")
            var env = ProcessInfo.processInfo.environment
            env["WORKSPACE_OS_ROOT"] = self.root.path
            process.environment = env
            process.standardOutput = self.logHandle; process.standardError = self.logHandle
            do { try process.run(); self.maintenance = process }
            catch { self.alert("无法打开高级工具", error.localizedDescription) }
        }
    }
    @objc func openLogs() { NSWorkspace.shared.open(fm.homeDirectoryForCurrentUser.appendingPathComponent("Library/Logs/WorkspaceOS")) }
    @objc func help() { NSWorkspace.shared.open(root.appendingPathComponent("docs/mac-app-2.0.6.md")) }
    @objc func about() { alert("Workspace OS 2.0.6 · Mac", "NEXUS 原生单入口\n本机内置 Python 服务 · 手动传输\n自动同步、自动删除、开机自启均未启用。") }
    func alert(_ title: String, _ message: String) {
        let dialog = NSAlert(); dialog.messageText = title; dialog.informativeText = message; dialog.runModal()
    }
    func applicationShouldHandleReopen(_ sender: NSApplication, hasVisibleWindows flag: Bool) -> Bool {
        window.makeKeyAndOrderFront(nil); return true
    }
    func applicationShouldTerminate(_ sender: NSApplication) -> NSApplication.TerminateReply {
        if maintenance?.isRunning == true {
            alert("高级工具仍在运行", "请先关闭高级控制中心，确认其任务已完成后再退出。")
            return .terminateCancel
        }
        requestJobs { [weak self] active in
            guard let self = self else { sender.reply(toApplicationShouldTerminate: true); return }
            if active == true {
                self.alert("传输仍在进行", "请等待任务完成后再退出。关闭窗口不会中断任务。")
                sender.reply(toApplicationShouldTerminate: false)
            } else if active == nil {
                self.alert("尚未确认任务状态", "请等待服务就绪后再退出，避免中断文件传输。")
                sender.reply(toApplicationShouldTerminate: false)
            } else {
                self.generation = UUID(); self.backend?.terminate()
                sender.reply(toApplicationShouldTerminate: true)
            }
        }
        return .terminateLater
    }
    func webView(_ webView: WKWebView, decidePolicyFor action: WKNavigationAction, decisionHandler: @escaping (WKNavigationActionPolicy) -> Void) {
        guard let url = action.request.url else { decisionHandler(.cancel); return }
        if action.shouldPerformDownload { decisionHandler(.download); return }
        if url.scheme == "http", url.host == "127.0.0.1", url.port == baseURL?.port {
            decisionHandler(.allow)
        } else {
            if ["https", "http"].contains(url.scheme ?? ""), action.navigationType == .linkActivated {
                NSWorkspace.shared.open(url)
            }
            decisionHandler(.cancel)
        }
    }
    func webView(_ webView: WKWebView, didFailProvisionalNavigation navigation: WKNavigation!, withError error: Error) {
        status.stringValue = "页面加载失败 · 可重新启动本地服务"
    }
    func webView(_ webView: WKWebView, runJavaScriptAlertPanelWithMessage message: String, initiatedByFrame frame: WKFrameInfo, completionHandler: @escaping () -> Void) {
        alert("NEXUS", message); completionHandler()
    }
    func webView(_ webView: WKWebView, runJavaScriptConfirmPanelWithMessage message: String, initiatedByFrame frame: WKFrameInfo, completionHandler: @escaping (Bool) -> Void) {
        let dialog = NSAlert(); dialog.messageText = "确认操作"; dialog.informativeText = message
        dialog.addButton(withTitle: "取消"); dialog.addButton(withTitle: "确认")
        completionHandler(dialog.runModal() == .alertSecondButtonReturn)
    }
    func webView(_ webView: WKWebView, navigationAction: WKNavigationAction, didBecome download: WKDownload) { download.delegate = self }
    func download(_ download: WKDownload, decideDestinationUsing response: URLResponse, suggestedFilename: String, completionHandler: @escaping (URL?) -> Void) {
        let panel = NSSavePanel(); panel.nameFieldStringValue = suggestedFilename
        panel.beginSheetModal(for: window) { result in completionHandler(result == .OK ? panel.url : nil) }
    }
    func download(_ download: WKDownload, didFailWithError error: Error, resumeData: Data?) { alert("导出失败", error.localizedDescription) }
}

let app = NSApplication.shared
let delegate = WorkspaceApp()
app.setActivationPolicy(.regular)
app.delegate = delegate
app.run()
