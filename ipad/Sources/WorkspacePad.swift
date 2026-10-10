import SwiftUI
import UniformTypeIdentifiers
import UIKit

struct Entry: Identifiable {
    let url: URL
    let directory: Bool
    var id: String { url.path }
}

@MainActor final class WorkspaceModel: ObservableObject {
    @Published var entries: [Entry] = []
    @Published var remote: URL?
    @Published var current: URL
    @Published var message = "仅手动操作 · 不自动同步、不覆盖、不删除"
    @Published var history: [String] = []
    let local: URL
    init() {
        local = FileManager.default.urls(for: .documentDirectory, in: .userDomainMask)[0].appendingPathComponent("Workspace", isDirectory: true)
        current = local
        do {
            for kind in ["Work", "Personal"] {
                for state in ["Active", "Paused", "Completed"] {
                    try FileManager.default.createDirectory(at: local.appendingPathComponent("01_Projects/\(kind)/\(state)"), withIntermediateDirectories: true)
                }
            }
        } catch { message = error.localizedDescription }
        history = UserDefaults.standard.stringArray(forKey: "history") ?? []
        refresh()
    }
    func log(_ value: String) {
        message = value
        history.insert("\(Date().formatted()) · \(value)", at: 0)
        history = Array(history.prefix(100))
        UserDefaults.standard.set(history, forKey: "history")
    }
    func refresh() {
        do {
            entries = try FileManager.default.contentsOfDirectory(at: current, includingPropertiesForKeys: [.isDirectoryKey], options: [.skipsHiddenFiles]).map {
                Entry(url: $0, directory: (try? $0.resourceValues(forKeys: [.isDirectoryKey]).isDirectory) == true)
            }.sorted { $0.directory != $1.directory ? $0.directory : $0.url.lastPathComponent.localizedStandardCompare($1.url.lastPathComponent) == .orderedAscending }
        } catch { entries = []; message = "无法读取：\(error.localizedDescription)" }
    }
    func authorize(_ url: URL) {
        guard url.startAccessingSecurityScopedResource() else { log("系统未授予目录访问权限，请重新选择。"); return }
        remote?.stopAccessingSecurityScopedResource()
        remote = url
        current = url
        log("已连接目录：\(url.lastPathComponent)；本次启动有效")
        refresh()
    }
}

struct DirectoryPicker: UIViewControllerRepresentable {
    let select: (URL) -> Void
    func makeCoordinator() -> Coordinator { Coordinator(select) }
    func makeUIViewController(context: Context) -> UIDocumentPickerViewController {
        let picker = UIDocumentPickerViewController(forOpeningContentTypes: [.folder])
        picker.delegate = context.coordinator
        return picker
    }
    func updateUIViewController(_ controller: UIDocumentPickerViewController, context: Context) {}
    final class Coordinator: NSObject, UIDocumentPickerDelegate {
        let select: (URL) -> Void
        init(_ select: @escaping (URL) -> Void) { self.select = select }
        func documentPicker(_ controller: UIDocumentPickerViewController, didPickDocumentsAt urls: [URL]) {
            if let first = urls.first { select(first) }
        }
    }
}

@main struct WorkspacePadApp: App {
    @StateObject private var model = WorkspaceModel()
    @State private var section = "工作区"
    @State private var picker = false
    @State private var search = ""
    @State private var quickConnect = ""
    @Environment(\.openURL) private var openURL
    private let sections = [("工作区", "square.grid.2x2"), ("NAS", "externaldrive.connected.to.line.below"), ("活动", "clock"), ("指南", "book")]
    var body: some Scene {
        WindowGroup {
            NavigationSplitView {
                VStack(alignment: .leading, spacing: 28) {
                    VStack(alignment: .leading, spacing: 8) {
                        Text("NEXUS").font(.system(size: 36, weight: .black, design: .rounded))
                        Text("WORKSPACE OS · iPAD").font(.caption).tracking(2).foregroundStyle(.secondary)
                    }.padding(.top, 30)
                    ForEach(sections, id: \.0) { item in
                        Button {
                            section = item.0
                            search = ""
                            if section == "工作区" { model.current = model.local; model.refresh() }
                            if section == "NAS", let remote = model.remote { model.current = remote; model.refresh() }
                        } label: {
                            Label(item.0, systemImage: item.1).font(.title3.weight(.medium)).frame(maxWidth: .infinity, alignment: .leading).padding(14)
                                .background(section == item.0 ? Color.cyan.opacity(0.13) : Color.clear, in: RoundedRectangle(cornerRadius: 16))
                        }.buttonStyle(.plain)
                    }
                    Spacer()
                    Label("手动管理 · 数据由你掌控", systemImage: "hand.raised").font(.caption).foregroundStyle(.secondary)
                    Text("1.0.0 Preview · iPadOS 16.5+").font(.caption2).foregroundStyle(.secondary)
                }.padding(24).background(Color(red: 0.035, green: 0.055, blue: 0.11))
            } detail: {
                VStack(alignment: .leading, spacing: 20) {
                    HStack {
                        VStack(alignment: .leading) {
                            Text(section).font(.largeTitle.bold())
                            Text(section == "工作区" ? "你的随身工作空间" : section == "NAS" ? "通过系统文件服务访问群晖" : "清晰、安全、可控").foregroundStyle(.secondary)
                        }
                        Spacer()
                        if section == "工作区" || section == "NAS" {
                            Button { model.refresh() } label: { Label("刷新", systemImage: "arrow.clockwise") }.buttonStyle(.bordered)
                        }
                    }
                    if section == "指南" { guide }
                    else if section == "活动" {
                        List { if model.history.isEmpty { Text("暂无操作记录") }; ForEach(Array(model.history.enumerated()), id: \.offset) { _, value in Text(value) } }.listStyle(.plain)
                    } else if section == "NAS" && model.remote == nil {
                        VStack(spacing: 22) {
                            Image(systemName: "externaldrive.badge.wifi").font(.system(size: 70)).foregroundStyle(.cyan)
                            Text("连接你的 Workspace").font(.title.bold())
                            Text("先在‘文件’App → 连接服务器中输入 NAS 地址，\n再在这里选择 Workspace 文件夹。账号密码由系统管理。").multilineTextAlignment(.center).foregroundStyle(.secondary)
                            Button("选择 NAS 文件夹") { picker = true }.buttonStyle(.borderedProminent)
                            Text("如果文件提供器不支持选择 SMB 文件夹，请在‘文件’App 中管理 NAS。此限制需要真机确认。").font(.caption).foregroundStyle(.secondary)
                        }.frame(maxWidth: .infinity, maxHeight: .infinity)
                    } else { browser }
                    Text(model.message).font(.footnote).foregroundStyle(.secondary).lineLimit(3)
                }.padding(30).background(Color(red: 0.055, green: 0.075, blue: 0.14))
            }.preferredColorScheme(.dark).tint(.cyan)
                .sheet(isPresented: $picker) { DirectoryPicker { model.authorize($0) } }
        }
    }
    private var browser: some View {
        VStack(alignment: .leading, spacing: 14) {
            HStack {
                Button { model.current.deleteLastPathComponent(); model.refresh() } label: { Image(systemName: "arrow.up") }
                    .disabled(model.current == model.local || model.current == model.remote)
                Text(model.current.lastPathComponent).font(.headline)
                Spacer()
                if section == "NAS" { Button("重新选择") { picker = true } }
            }
            TextField("搜索当前目录", text: $search).textFieldStyle(.roundedBorder)
            List(model.entries.filter { search.isEmpty || $0.url.lastPathComponent.localizedCaseInsensitiveContains(search) }) { entry in
                HStack(spacing: 16) {
                    Image(systemName: entry.directory ? "folder.fill" : "doc").font(.title2).foregroundStyle(entry.directory ? .cyan : .gray)
                    VStack(alignment: .leading, spacing: 4) {
                        Text(entry.url.lastPathComponent)
                        if let alias = ["01_Projects": "项目", "Work": "工作", "Personal": "生活", "Active": "进行中", "Paused": "已暂停", "Completed": "已完成"][entry.url.lastPathComponent] { Text(alias).font(.caption).foregroundStyle(.secondary) }
                    }
                    Spacer()
                    if entry.directory { Image(systemName: "chevron.right").foregroundStyle(.secondary) }
                }.padding(.vertical, 8).contentShape(Rectangle()).onTapGesture {
                    if entry.directory { model.current = entry.url; model.refresh() }
                    else { model.message = "文件操作请使用系统‘文件’App；此预览版不修改 NAS 文件。" }
                }
            }.listStyle(.plain)
        }
    }
    private var guide: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 24) {
                Text("01  本地与 NAS，各司其职").font(.title2.bold())
                Text("本地目录位于‘文件 → 我的 iPad → Workspace OS → Workspace’。项目结构与 Mac / Windows 一致。此预览版提供目录浏览、搜索和授权入口；上传、下载、对比和同步暂未实现，请通过系统‘文件’App 手动复制，遇到同名文件取消替换。")
                Text("02  连接群晖").font(.title2.bold())
                Text("同一局域网下，在‘文件’App 的连接服务器中输入 smb://192.168.1.9；外网请使用你已配置的 VPN 地址。QuickConnect 是网页访问入口，不是 SMB 挂载。")
                TextField("QuickConnect ID（不含网址）", text: $quickConnect).textFieldStyle(.roundedBorder).textInputAutocapitalization(.never).autocorrectionDisabled()
                Button("在浏览器打开 QuickConnect") {
                    let value = quickConnect.trimmingCharacters(in: .whitespacesAndNewlines)
                    guard !value.isEmpty, value.range(of: "^[A-Za-z0-9-]+$", options: .regularExpression) != nil,
                          let url = URL(string: "https://quickconnect.to/\(value)") else { model.message = "请输入仅包含字母、数字或连字符的 QuickConnect ID"; return }
                    openURL(url)
                }.buttonStyle(.bordered)
                Text("03  安全边界").font(.title2.bold())
                Text("不保存 NAS 密码；不配置自动同步、覆盖或删除；不更改共享权限。NAS 授权仅本次启动有效。卸载应用可能删除本地工作区，请先在‘文件’App 中另存重要资料。iPad 沙盒无法直接使用 Mac 的 Python 后台。")
            }.frame(maxWidth: 850, alignment: .leading)
        }
    }
}
