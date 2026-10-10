package com.workspaceos.mobile

import android.app.Application
import android.content.Intent
import android.net.Uri
import android.widget.Toast
import androidx.core.content.FileProvider
import androidx.lifecycle.AndroidViewModel
import androidx.lifecycle.viewModelScope
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.Job
import kotlinx.coroutines.delay
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.launch
import java.io.File

enum class WorkspacePage { NAS, PHONE }

enum class SortKey(val label: String) { NAME("名称"), SIZE("大小"), TIME("时间") }

enum class PreviewKind { IMAGE, MARKDOWN, TEXT }

data class PreviewState(val name: String, val kind: PreviewKind, val uri: Uri, val text: String? = null)

data class WorkspaceUiState(
    val page: WorkspacePage = WorkspacePage.NAS,
    val settings: WorkspaceSettings = WorkspaceSettings(),
    val configExpanded: Boolean = true,
    val connected: Boolean = false,
    val busy: Boolean = false,
    val currentPath: String = "",
    val entries: List<RemoteEntry> = emptyList(),
    val selected: Set<String> = emptySet(),
    val search: String = "",
    val localRootUri: String? = null,
    val localRootName: String = "手机文件",
    val localPath: List<String> = emptyList(),
    val localEntries: List<LocalEntry> = emptyList(),
    val localSelected: Set<String> = emptySet(),
    val localSearch: String = "",
    val nasStorage: StorageInfo = StorageInfo(),
    val phoneStorage: StorageInfo = StorageInfo(),
    val status: String = "等待连接 NAS",
    val toast: String? = null,
    val downloadDir: String = "",
    val downloadTreeUri: String? = null,
    val downloadTreeName: String = "",
    val sortKey: SortKey = SortKey.NAME,
    val sortAsc: Boolean = true,
    val recentSynced: List<SyncedFile> = emptyList(),
    val preview: PreviewState? = null,
    val task: TransferState? = null
) {
    val endpoint: NasEndpoint get() = settings.active
    val downloadDirLabel: String
        get() = when {
            downloadTreeUri != null -> "已选目录 · $downloadTreeName"
            downloadDir.isNotBlank() -> "Download / $downloadDir"
            else -> "Download / WorkspaceOS（默认）"
        }
    val downloadDirHint: String
        get() = when {
            downloadTreeUri != null -> "NAS 文件将镜像目录结构写入所选文件夹"
            else -> "保留 NAS 原目录层级"
        }
    val downloadTarget: DownloadTarget
        get() = downloadTreeUri?.let(Uri::parse)?.let { DownloadTarget.Tree(it) } ?: DownloadTarget.DownloadsFolder(downloadDir)
}

class WorkspaceViewModel(application: Application) : AndroidViewModel(application) {
    private val settings = SecureSettings(application)
    private val smbRepository = SmbRepository(application)
    private val localRepository = LocalFileRepository(application)
    private val preferences = application.getSharedPreferences("workspace-os-local-files", Application.MODE_PRIVATE)
    private val savedSettings = settings.load()
    private val savedRoot = localRepository.savedRootUri()
    private val mutableState = MutableStateFlow(
        WorkspaceUiState(
            settings = savedSettings,
            configExpanded = savedSettings.active.username.isBlank(),
            localRootUri = savedRoot?.toString(),
            phoneStorage = smbRepository.phoneStorageInfo(),
            downloadDir = preferences.getString("download_dir", "").orEmpty(),
            downloadTreeUri = preferences.getString("download_tree", null),
            downloadTreeName = preferences.getString("download_tree_name", "").orEmpty(),
            sortKey = runCatching { SortKey.valueOf(preferences.getString("sort_key", "NAME") ?: "NAME") }.getOrDefault(SortKey.NAME),
            sortAsc = preferences.getBoolean("sort_asc", true)
        )
    )
    val state: StateFlow<WorkspaceUiState> = mutableState.asStateFlow()

    private var taskJob: Job? = null
    private var consecutiveErrors = 0

    init {
        if (savedRoot != null) viewModelScope.launch { refreshLocalInternal("手机目录已载入") }
        viewModelScope.launch { prunePreviewCache() }
    }

    // ---- settings & profiles -------------------------------------------------

    fun updateConfig(endpoint: NasEndpoint) = mutableState.update {
        it.copy(settings = it.settings.copy(endpoints = it.settings.endpoints.map { e -> if (e.id == it.endpoint.id) endpoint else e }))
    }

    fun setConfigExpanded(expanded: Boolean) = mutableState.update { it.copy(configExpanded = expanded) }

    fun switchProfile(id: String) = mutableState.update { current ->
        if (id == current.settings.activeId) current
        else current.copy(
            settings = current.settings.copy(activeId = id),
            configExpanded = true,
            connected = false,
            entries = emptyList(),
            selected = emptySet(),
            nasStorage = StorageInfo(),
            status = "已切换连接档，点击连接"
        )
    }.also { saveSettings() }

    fun addProfile() = mutableState.update { current ->
        val id = "profile-" + System.currentTimeMillis()
        val fresh = NasEndpoint(id = id, name = "NAS ${current.settings.endpoints.size + 1}")
        current.copy(
            settings = current.settings.copy(endpoints = current.settings.endpoints + fresh, activeId = id),
            configExpanded = true,
            connected = false,
            entries = emptyList(),
            selected = emptySet(),
            status = "填写 NAS 地址后点击连接"
        )
    }.also { saveSettings() }

    fun deleteActiveProfile() = mutableState.update { current ->
        val remaining = current.settings.endpoints.filterNot { it.id == current.settings.activeId }
        if (remaining.isEmpty()) {
            current.copy(settings = WorkspaceSettings(listOf(NasEndpoint()), "default"), connected = false, status = "已删除连接档")
        } else {
            current.copy(settings = WorkspaceSettings(remaining, remaining.first().id), connected = false, entries = emptyList(), status = "已删除连接档")
        }
    }.also { saveSettings() }

    fun setDownloadDir(dir: String) {
        val clean = dir.trim().trim('/').replace('\\', '/')
        preferences.edit().putString("download_dir", clean).apply()
        mutableState.update { it.copy(downloadDir = clean) }
    }

    fun setDownloadTree(uri: Uri) = viewModelScope.launch {
        runCatching {
            localRepository.persistPermission(uri)
            val name = androidx.documentfile.provider.DocumentFile.fromTreeUri(getApplication(), uri)?.name ?: "所选目录"
            preferences.edit().putString("download_tree", uri.toString()).putString("download_tree_name", name).apply()
            mutableState.update { it.copy(downloadTreeUri = uri.toString(), downloadTreeName = name, toast = "下载目录已设为：$name") }
        }.onFailure(::publishFailure)
    }

    fun clearDownloadTree() {
        preferences.edit().remove("download_tree").remove("download_tree_name").apply()
        mutableState.update { it.copy(downloadTreeUri = null, downloadTreeName = "", toast = "已恢复默认下载目录 Download/WorkspaceOS") }
    }

    private fun saveSettings() = viewModelScope.launch { runCatching { settings.save(state.value.settings) } }

    fun setSearch(value: String) = mutableState.update { it.copy(search = value) }
    fun setLocalSearch(value: String) = mutableState.update { it.copy(localSearch = value) }
    fun setPage(page: WorkspacePage) = mutableState.update { it.copy(page = page) }

    fun setSort(key: SortKey) {
        val current = state.value
        val nextAsc = if (current.sortKey == key) !current.sortAsc else true
        preferences.edit().putString("sort_key", key.name).putBoolean("sort_asc", nextAsc).apply()
        mutableState.update { it.copy(sortKey = key, sortAsc = nextAsc) }
        applySortToVisible()
    }

    private fun applySortToVisible() = mutableState.update { current ->
        current.copy(entries = sortRemote(current.entries, current.sortKey, current.sortAsc))
    }

    // ---- NAS -----------------------------------------------------------------

    fun connect() = viewModelScope.launch {
        val config = state.value.endpoint
        val cleaned = config.copy(host = config.host.trim(), share = config.share.trim(), name = config.name.trim())
        mutableState.update { it.copy(settings = it.settings.replaceActive(cleaned), busy = true, status = "正在连接 NAS…") }
        saveSettings()
        runCatching { smbRepository.browse(cleaned, state.value.currentPath) }
            .onSuccess { result ->
                consecutiveErrors = 0
                mutableState.update {
                    it.copy(
                        connected = true,
                        busy = false,
                        configExpanded = false,
                        entries = sortRemote(result.entries, it.sortKey, it.sortAsc),
                        selected = emptySet(),
                        nasStorage = result.nasStorage,
                        phoneStorage = result.phoneStorage,
                        status = "NAS 已连接 · ${result.entries.size} 项"
                    )
                }
            }
            .onFailure { error ->
                consecutiveErrors++
                if (consecutiveErrors >= 2) mutableState.update { it.copy(connected = false) }
                mutableState.update { it.copy(busy = false, status = friendlyError(error)) }
            }
    }

    fun refresh() = viewModelScope.launch { refreshRemoteInternal("NAS 目录已刷新") }

    fun open(entry: RemoteEntry) {
        if (!entry.directory || state.value.busy) return
        mutableState.update { it.copy(currentPath = entry.relative, selected = emptySet()) }
        refresh()
    }

    fun up() {
        val path = state.value.currentPath.substringBeforeLast('/', "")
        mutableState.update { it.copy(currentPath = path, selected = emptySet()) }
        refresh()
    }

    fun goRoot() {
        if (state.value.currentPath.isBlank() || state.value.busy) return
        mutableState.update { it.copy(currentPath = "", selected = emptySet()) }
        refresh()
    }

    /** Preview a remote file in-app (image/markdown/text); other types launch a system viewer. */
    fun openRemote(entry: RemoteEntry) = viewModelScope.launch {
        if (entry.directory || state.value.busy) return@launch
        if (entry.size > PREVIEW_LIMIT_BYTES) {
            toastNow("文件超过 64 MB，请先「同步到手机」后在本机打开")
            return@launch
        }
        val config = state.value.endpoint
        val file = previewFile(entry.relative)
        mutableState.update { it.copy(busy = true, status = "正在加载预览 · ${entry.name}") }
        try {
            val fresh = file.exists() && file.length() == entry.size &&
                (entry.modifiedMillis <= 0 || file.lastModified() >= entry.modifiedMillis - 2_000)
            if (!fresh) {
                file.parentFile?.mkdirs()
                smbRepository.downloadTo(config, entry, file)
            }
        } catch (error: Throwable) {
            file.delete()
            if (error is CancellationException) {
                mutableState.update { it.copy(busy = false) }
            } else {
                val message = friendlyError(error)
                mutableState.update { it.copy(busy = false, status = message, toast = message) }
            }
            return@launch
        }
        val uri = FileProvider.getUriForFile(getApplication(), "${getApplication<Application>().packageName}.fileprovider", file)
        presentPreview(entry.name, uri)
    }

    /** Preview a phone file in-app when supported, otherwise open with a system viewer. */
    fun previewLocal(entry: LocalEntry) = viewModelScope.launch {
        if (entry.directory || state.value.busy) return@launch
        val root = state.value.localRootUri?.let(Uri::parse) ?: return@launch
        val uri = entry.documentUri?.let(Uri::parse) ?: localRepository.resolveLocalUri(root, entry.relative)
        if (uri == null) {
            toastNow("找不到该文件，请刷新后重试")
            return@launch
        }
        presentPreview(entry.name, uri)
    }

    private fun presentPreview(name: String, uri: Uri) {
        val kind = previewKindFor(name)
        if (kind == null) {
            val intent = Intent(Intent.ACTION_VIEW).apply {
                setDataAndType(uri, mimeTypeFor(name))
                addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION or Intent.FLAG_ACTIVITY_NEW_TASK)
            }
            launchView(intent, name)
            mutableState.update { it.copy(busy = false, status = "打开 · $name") }
            return
        }
        viewModelScope.launch {
            runCatching {
                if (kind == PreviewKind.TEXT || kind == PreviewKind.MARKDOWN) readTextFrom(uri) else null
            }.onSuccess { text ->
                mutableState.update {
                    it.copy(
                        busy = false,
                        preview = PreviewState(name, kind, uri, text)
                    )
                }
            }.onFailure {
                toastNow("无法读取 $name，请尝试用其他应用打开")
                mutableState.update { it.copy(busy = false) }
            }
        }
    }

    fun closePreview() = mutableState.update { it.copy(preview = null) }

    fun openPreviewExternally(preview: PreviewState) {
        val intent = Intent(Intent.ACTION_VIEW).apply {
            setDataAndType(preview.uri, mimeTypeFor(preview.name))
            addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION or Intent.FLAG_ACTIVITY_NEW_TASK)
        }
        launchView(intent, preview.name)
    }

    private suspend fun readTextFrom(uri: Uri): String = kotlinx.coroutines.withContext(kotlinx.coroutines.Dispatchers.IO) {
        val input = checkNotNull(context().contentResolver.openInputStream(uri)) { "无法读取文件" }
        input.use { it.readBytes().toString(Charsets.UTF_8).take(2_000_000) }
    }

    private fun context(): Application = getApplication()

    companion object {
        private const val PREVIEW_LIMIT_BYTES = 64L * 1024 * 1024

        fun previewKindFor(name: String): PreviewKind? {
            val ext = name.substringAfterLast('.', "").lowercase()
            return when (ext) {
                "jpg", "jpeg", "png", "gif", "webp", "bmp" -> PreviewKind.IMAGE
                "md", "markdown" -> PreviewKind.MARKDOWN
                "txt", "log", "csv", "json", "yaml", "yml", "xml", "html", "htm" -> PreviewKind.TEXT
                else -> null
            }
        }
    }

    fun toggleSelected(entry: RemoteEntry) = mutableState.update { current ->
        val next = current.selected.toMutableSet()
        if (!next.add(entry.relative)) next.remove(entry.relative)
        current.copy(selected = next)
    }

    fun selectAllVisible() = mutableState.update { current ->
        val query = current.search.trim()
        val paths = current.entries
            .filter { query.isBlank() || it.name.contains(query, ignoreCase = true) }
            .mapTo(linkedSetOf()) { it.relative }
        current.copy(selected = if (paths.isNotEmpty() && paths.all { it in current.selected }) current.selected - paths else current.selected + paths)
    }

    fun clearSelection() = mutableState.update { it.copy(selected = emptySet()) }

    fun createFolder(name: String) = viewModelScope.launch {
        val snapshot = state.value
        mutableState.update { it.copy(busy = true, status = "正在创建 NAS 文件夹…") }
        runCatching { smbRepository.createFolder(snapshot.endpoint, snapshot.currentPath, name) }
            .onSuccess { refreshRemoteInternal("文件夹已创建：${name.trim()}") }
            .onFailure(::publishFailure)
    }

    fun renameRemote(entry: RemoteEntry, newName: String) = viewModelScope.launch {
        val clean = newName.trim().replace('\\', '_').replace('/', '_')
        require(clean.isNotBlank()) { "名称不能为空" }
        val config = state.value.endpoint
        runCatching { smbRepository.renameRemote(config, entry, clean) }
            .onSuccess { refreshRemoteInternal("已重命名为 ${clean}") }
            .onFailure(::publishFailure)
    }

    fun deleteRemote(entries: List<RemoteEntry>) = launchTask("删除 NAS 项目") { config, report ->
        smbRepository.deleteRemote(config, entries, report)
        refreshRemoteInternal("NAS 项目已删除")
    }

    fun uploadUris(uris: List<Uri>) = launchTask("上传到 NAS") { config, report ->
        if (uris.isEmpty()) return@launchTask
        val selection = smbRepository.describeDocuments(uris)
        require(!selection.isEmpty) { "没有可上传的文件" }
        val snapshot = state.value
        smbRepository.upload(config, snapshot.currentPath, selection, report)
        smbRepository.appendSyncLog(config, "to_nas", "safe", selection.files.map { it.relativePath })
        refreshRemoteInternal("上传完成，NAS 目录已刷新")
    }

    fun syncSelected() = launchTask("同步到手机") { config, report ->
        val snapshot = state.value
        val entries = snapshot.entries.filter { it.relative in snapshot.selected }
        require(entries.isNotEmpty()) { "请先勾选需要同步到手机的文件或文件夹" }
        val synced = smbRepository.download(config, entries, snapshot.downloadTarget, report)
        smbRepository.appendSyncLog(config, "to_computer", "safe", entries.map { it.relative })
        publishRecentSynced(synced)
    }

    fun download(entry: RemoteEntry) = launchTask("同步到手机") { config, report ->
        val synced = smbRepository.download(config, listOf(entry), state.value.downloadTarget, report)
        smbRepository.appendSyncLog(config, "to_computer", "safe", listOf(entry.relative))
        publishRecentSynced(synced)
    }

    private fun publishRecentSynced(synced: List<SyncedFile>) {
        if (synced.isEmpty()) return
        val label = downloadLabel()
        val message = if (synced.size == 1) "已保存到 $label · 点「打开」查看" else "${synced.size} 项已保存到 $label · 点「打开」查看"
        mutableState.update {
            it.copy(
                selected = emptySet(),
                phoneStorage = smbRepository.phoneStorageInfo(),
                recentSynced = (synced + it.recentSynced).distinctBy { file -> file.relative }.take(8),
                toast = message
            )
        }
    }

    /** Open a file that lives on the phone (just-synced or local); supported types preview in-app. */
    fun openSynced(file: SyncedFile) {
        presentPreview(file.name, file.uri)
    }

    fun clearRecentSynced() = mutableState.update { it.copy(recentSynced = emptyList()) }

    private fun launchView(intent: Intent, name: String) {
        try {
            getApplication<Application>().startActivity(
                Intent.createChooser(intent, "打开 $name").addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
            )
        } catch (error: Throwable) {
            if (error is CancellationException) return
            toastNow("没有能打开 $name 的应用，可在应用商店安装对应格式播放器")
        }
    }

    private fun downloadLabel(): String {
        val current = state.value
        return when {
            current.downloadTreeUri != null -> "「${current.downloadTreeName}」"
            else -> "Download/${current.downloadDir.trim('/').ifBlank { "WorkspaceOS" }}"
        }
    }

    // ---- local ---------------------------------------------------------------

    fun chooseLocalRoot(uri: Uri) = viewModelScope.launch {
        runCatching {
            localRepository.persistRoot(uri)
            mutableState.update { it.copy(localRootUri = uri.toString(), localPath = emptyList(), localSelected = emptySet(), page = WorkspacePage.PHONE) }
            refreshLocalInternal("手机目录已授权")
        }.onFailure(::publishFailure)
    }

    fun refreshLocal() = viewModelScope.launch { refreshLocalInternal("手机目录已刷新") }

    fun openLocal(entry: LocalEntry) {
        if (state.value.busy) return
        if (entry.directory) {
            mutableState.update { it.copy(localPath = it.localPath + entry.name, localSelected = emptySet()) }
            refreshLocal()
            return
        }
        viewModelScope.launch {
            val root = state.value.localRootUri?.let(Uri::parse) ?: return@launch
            val uri = entry.documentUri?.let(Uri::parse) ?: localRepository.resolveLocalUri(root, entry.relative)
            if (uri == null) {
                toastNow("找不到该文件，请刷新后重试")
                return@launch
            }
            val kind = previewKindFor(entry.name)
            if (kind != null) {
                presentPreview(entry.name, uri)
                return@launch
            }
            val intent = Intent(Intent.ACTION_VIEW).apply {
                setDataAndType(uri, entry.mimeType?.takeIf { mime -> mime.isNotBlank() && mime != "*/*" } ?: mimeTypeFor(entry.name))
                addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION or Intent.FLAG_ACTIVITY_NEW_TASK)
            }
            launchView(intent, entry.name)
        }
    }

    fun localUp() {
        if (state.value.localPath.isEmpty()) return
        mutableState.update { it.copy(localPath = it.localPath.dropLast(1), localSelected = emptySet()) }
        refreshLocal()
    }

    fun goLocalRoot() {
        if (state.value.localPath.isEmpty() || state.value.busy) return
        mutableState.update { it.copy(localPath = emptyList(), localSelected = emptySet()) }
        refreshLocal()
    }

    fun createLocalFolder(name: String) = viewModelScope.launch {
        val snapshot = state.value
        val root = snapshot.localRootUri?.let(Uri::parse) ?: return@launch
        mutableState.update { it.copy(busy = true, status = "正在创建手机文件夹…") }
        runCatching { localRepository.createFolder(root, snapshot.localPath, name) }
            .onSuccess { refreshLocalInternal("手机文件夹已创建：${name.trim()}") }
            .onFailure(::publishFailure)
    }

    fun duplicateLocal(entry: LocalEntry, newName: String) = launchTask("创建副本") { _, report ->
        val root = state.value.localRootUri?.let(Uri::parse) ?: return@launchTask
        localRepository.duplicate(root, entry, newName, report)
        refreshLocalInternal("副本已创建")
    }

    fun renameLocal(entry: LocalEntry, newName: String) = launchTask("重命名") { _, report ->
        val root = state.value.localRootUri?.let(Uri::parse) ?: return@launchTask
        localRepository.rename(root, entry, newName, report)
        refreshLocalInternal("已重命名为 ${newName.trim()}")
    }

    fun toggleLocalSelected(entry: LocalEntry) = mutableState.update { current ->
        val next = current.localSelected.toMutableSet()
        if (!next.add(entry.relative)) next.remove(entry.relative)
        current.copy(localSelected = next)
    }

    fun selectAllLocal() = mutableState.update { current ->
        val query = current.localSearch.trim()
        val paths = current.localEntries
            .filter { query.isBlank() || it.name.contains(query, ignoreCase = true) }
            .mapTo(linkedSetOf()) { it.relative }
        current.copy(localSelected = if (paths.isNotEmpty() && paths.all { it in current.localSelected }) current.localSelected - paths else current.localSelected + paths)
    }

    fun deleteLocal(entries: List<LocalEntry>) = launchTask("删除手机项目") { _, report ->
        val root = state.value.localRootUri?.let(Uri::parse) ?: return@launchTask
        localRepository.delete(root, entries, report)
        refreshLocalInternal("手机项目已删除")
    }

    fun copyLocalSelected(destinationUri: Uri) = launchTask("复制手机文件") { _, report ->
        val snapshot = state.value
        val root = snapshot.localRootUri?.let(Uri::parse) ?: return@launchTask
        val entries = snapshot.localEntries.filter { it.relative in snapshot.localSelected }
        require(entries.isNotEmpty()) { "请先勾选要复制的文件或文件夹" }
        localRepository.persistPermission(destinationUri)
        localRepository.copy(root, entries, destinationUri, report)
        mutableState.update { it.copy(localSelected = emptySet(), phoneStorage = smbRepository.phoneStorageInfo(), toast = "手机文件复制完成") }
    }

    fun uploadLocalSelected() = launchTask("上传到 NAS") { _, report ->
        val snapshot = state.value
        require(snapshot.connected) { "请先连接 NAS，再上传手机文件" }
        val root = snapshot.localRootUri?.let(Uri::parse) ?: return@launchTask
        val entries = snapshot.localEntries.filter { it.relative in snapshot.localSelected }
        require(entries.isNotEmpty()) { "请先勾选要上传的文件或文件夹" }
        val selection = localRepository.buildUploadSelection(root, entries)
        smbRepository.upload(snapshot.endpoint, snapshot.currentPath, selection, report)
        smbRepository.appendSyncLog(snapshot.endpoint, "to_nas", "safe", selection.files.map { it.relativePath })
        mutableState.update { it.copy(localSelected = emptySet(), status = "已上传到 NAS /${snapshot.currentPath}") }
        refreshRemoteInternal("NAS 目录已刷新")
    }

    // ---- task control ----------------------------------------------------------

    fun cancelTask() {
        val running = taskJob ?: return
        if (state.value.task?.completed == true || state.value.task?.failed == true) return
        running.cancel()
        mutableState.update {
            it.copy(
                busy = false,
                status = "已取消任务",
                task = it.task?.copy(failed = true, completed = false, message = "已取消")
            )
        }
        taskJob = null
    }

    fun clearTask() = mutableState.update { it.copy(task = null) }

    fun consumeToast() = mutableState.update { it.copy(toast = null) }

    private fun launchTask(title: String, block: suspend (NasEndpoint, (TransferState) -> Unit) -> Unit) {
        taskJob?.cancel()
        taskJob = viewModelScope.launch {
            mutableState.update { it.copy(busy = true, task = TransferState(title)) }
            runCatching { block(state.value.endpoint, ::publishTask) }
                .onFailure { error ->
                    if (error is CancellationException) {
                        mutableState.update { it.copy(busy = false) }
                    } else {
                        publishFailure(error)
                    }
                }
        }
    }

    // ---- internals --------------------------------------------------------------

    private suspend fun refreshRemoteInternal(message: String) {
        val snapshot = state.value
        if (!snapshot.endpoint.ready) return
        mutableState.update { it.copy(busy = true) }
        runCatching { smbRepository.browse(snapshot.endpoint, snapshot.currentPath) }
            .onSuccess { result ->
                consecutiveErrors = 0
                mutableState.update {
                    it.copy(
                        connected = true,
                        busy = false,
                        entries = sortRemote(result.entries, it.sortKey, it.sortAsc),
                        selected = emptySet(),
                        nasStorage = result.nasStorage,
                        phoneStorage = result.phoneStorage,
                        status = "$message · ${result.entries.size} 项"
                    )
                }
            }
            .onFailure { error ->
                consecutiveErrors++
                val dropConnection = consecutiveErrors >= 2
                mutableState.update {
                    it.copy(
                        busy = false,
                        connected = if (dropConnection) false else it.connected,
                        status = friendlyError(error)
                    )
                }
            }
    }

    private suspend fun refreshLocalInternal(message: String) {
        val snapshot = state.value
        val root = snapshot.localRootUri?.let(Uri::parse) ?: return
        mutableState.update { it.copy(busy = true) }
        runCatching { localRepository.browse(root, snapshot.localPath) }
            .onSuccess { result ->
                mutableState.update {
                    it.copy(
                        busy = false,
                        localRootName = result.rootName,
                        localEntries = sortLocal(result.entries, it.sortKey, it.sortAsc),
                        localSelected = emptySet(),
                        phoneStorage = smbRepository.phoneStorageInfo(),
                        status = "$message · ${result.entries.size} 项"
                    )
                }
            }
            .onFailure { error -> mutableState.update { it.copy(busy = false, status = friendlyError(error)) } }
    }

    private fun sortRemote(entries: List<RemoteEntry>, key: SortKey, asc: Boolean): List<RemoteEntry> {
        val groups = entries.sortedWith(
            when (key) {
                SortKey.NAME -> compareBy(String.CASE_INSENSITIVE_ORDER) { it.name }
                SortKey.SIZE -> compareByDescending { it.size }
                SortKey.TIME -> compareByDescending { it.modifiedMillis }
            }
        )
        val ordered = if (asc) groups else groups.reversed()
        return ordered.sortedByDescending { it.directory }
    }

    private fun sortLocal(entries: List<LocalEntry>, key: SortKey, asc: Boolean): List<LocalEntry> {
        val groups = entries.sortedWith(
            when (key) {
                SortKey.NAME -> compareBy(String.CASE_INSENSITIVE_ORDER) { it.name }
                SortKey.SIZE -> compareByDescending { it.size }
                SortKey.TIME -> compareByDescending { it.modifiedMillis }
            }
        )
        val ordered = if (asc) groups else groups.reversed()
        return ordered.sortedByDescending { it.directory }
    }

    private fun previewFile(relative: String): File {
        val name = relative.substringAfterLast('/').ifBlank { "preview" }
        val key = relative.hashCode().toString(16)
        return File(File(getApplication<Application>().cacheDir, "workspaceos-previews"), "$key-$name")
    }

    private suspend fun prunePreviewCache() {
        val root = File(getApplication<Application>().cacheDir, "workspaceos-previews")
        val cutoff = System.currentTimeMillis() - 24 * 60 * 60 * 1000
        root.listFiles()?.filter { it.lastModified() < cutoff }?.forEach { it.delete() }
    }

    private fun toastNow(message: String) = mutableState.update { it.copy(toast = message) }

    private fun publishTask(task: TransferState) = mutableState.update {
        it.copy(task = task, busy = !task.completed && !task.failed, status = task.message.ifBlank { "${task.title} · ${task.currentFile}" })
    }

    private fun publishFailure(error: Throwable) {
        if (error is CancellationException) return
        val message = friendlyError(error)
        val previous = state.value.task
        mutableState.update {
            it.copy(
                busy = false,
                status = message,
                toast = if (previous == null) null else message,
                task = (previous ?: TransferState("文件任务")).copy(failed = true, completed = false, message = message)
            )
        }
    }

    private fun friendlyError(error: Throwable): String {
        val raw = generateSequence(error) { it.cause }.mapNotNull { it.message }.firstOrNull { it.isNotBlank() }.orEmpty()
        return when {
            raw.contains("STATUS_LOGON_FAILURE", true) -> "NAS 登录失败，请检查用户名和密码"
            raw.contains("STATUS_BAD_NETWORK_NAME", true) -> "找不到共享文件夹，请检查共享名"
            raw.contains("timed out", true) || raw.contains("timeout", true) -> "连接超时，请检查 ZeroTier/Wi-Fi 和 NAS 地址"
            raw.contains("refused", true) -> "NAS 拒绝连接，请确认 SMB 服务已开启"
            raw.contains("STATUS_OBJECT_NAME_NOT_FOUND", true) || raw.contains("does not exist", true) -> "文件不存在，可能已被移动或删除，请刷新目录"
            raw.contains("permission", true) || raw.contains("denied", true) -> "没有文件操作权限，请重新选择并授权目录"
            raw.contains("Unable to resolve", true) -> "无法解析 NAS 地址，请检查网络"
            else -> "操作失败：${raw.ifBlank { error.javaClass.simpleName }}"
        }
    }

    class Factory(private val application: Application) : androidx.lifecycle.ViewModelProvider.Factory {
        @Suppress("UNCHECKED_CAST")
        override fun <T : androidx.lifecycle.ViewModel> create(modelClass: Class<T>): T = WorkspaceViewModel(application) as T
    }
}

private fun WorkspaceSettings.replaceActive(endpoint: NasEndpoint): WorkspaceSettings =
    copy(endpoints = endpoints.map { if (it.id == activeId) endpoint else it })

private fun mimeTypeFor(name: String): String {
    val ext = name.substringAfterLast('.', "").lowercase()
    return when (ext) {
        "jpg", "jpeg" -> "image/jpeg"
        "png" -> "image/png"
        "gif" -> "image/gif"
        "webp" -> "image/webp"
        "bmp" -> "image/bmp"
        "svg" -> "image/svg+xml"
        "heic" -> "image/heic"
        "mp4" -> "video/mp4"
        "mkv" -> "video/x-matroska"
        "mov" -> "video/quicktime"
        "avi" -> "video/avi"
        "webm" -> "video/webm"
        "mp3" -> "audio/mpeg"
        "flac" -> "audio/flac"
        "wav" -> "audio/wav"
        "aac" -> "audio/aac"
        "ogg" -> "audio/ogg"
        "pdf" -> "application/pdf"
        "txt", "md", "log", "csv" -> "text/plain"
        "json" -> "application/json"
        "html", "htm" -> "text/html"
        "zip" -> "application/zip"
        "apk" -> "application/vnd.android.package-archive"
        "doc" -> "application/msword"
        "docx" -> "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
        "xls" -> "application/vnd.ms-excel"
        "xlsx" -> "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        "ppt" -> "application/vnd.ms-powerpoint"
        "pptx" -> "application/vnd.openxmlformats-officedocument.presentationml.presentation"
        else -> "*/*"
    }
}
