package com.workspaceos.mobile

import android.content.Context
import android.content.Intent
import android.net.Uri
import android.provider.DocumentsContract
import androidx.documentfile.provider.DocumentFile
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.currentCoroutineContext
import kotlinx.coroutines.ensureActive
import kotlinx.coroutines.withContext

data class LocalEntry(
    val name: String,
    val relative: String,
    val directory: Boolean,
    val size: Long,
    val modifiedMillis: Long,
    val mimeType: String?,
    val documentUri: String? = null
)

data class LocalBrowseResult(
    val rootName: String,
    val entries: List<LocalEntry>
)

data class UploadSelection(
    val directories: List<String> = emptyList(),
    val files: List<LocalDocument> = emptyList()
) {
    val isEmpty: Boolean get() = directories.isEmpty() && files.isEmpty()
}

private data class LocalPlan(
    val directories: LinkedHashMap<String, DocumentFile> = linkedMapOf(),
    val files: LinkedHashMap<String, DocumentFile> = linkedMapOf()
)

class LocalFileRepository(private val context: Context) {
    private val preferences = context.getSharedPreferences("workspace-os-local-files", Context.MODE_PRIVATE)

    fun savedRootUri(): Uri? = preferences.getString("root_uri", null)?.let(Uri::parse)

    fun persistRoot(uri: Uri) {
        persistPermission(uri)
        preferences.edit().putString("root_uri", uri.toString()).apply()
    }

    fun persistPermission(uri: Uri) {
        val flags = Intent.FLAG_GRANT_READ_URI_PERMISSION or Intent.FLAG_GRANT_WRITE_URI_PERMISSION
        runCatching { context.contentResolver.takePersistableUriPermission(uri, flags) }
    }

    suspend fun browse(rootUri: Uri, path: List<String>): LocalBrowseResult = withContext(Dispatchers.IO) {
        val root = requireNotNull(DocumentFile.fromTreeUri(context, rootUri)) { "无法打开手机目录" }
        val current = requireNotNull(resolve(root, path)) { "手机目录已移动或无权访问" }
        require(current.isDirectory) { "所选位置不是文件夹" }
        val prefix = path.joinToString("/")
        // A single children query replaces per-item length()/lastModified() round trips.
        val entries = queryChildren(current.uri, prefix) ?: legacyChildren(current, prefix)
        LocalBrowseResult(
            root.name ?: "手机文件",
            entries.sortedWith(compareByDescending<LocalEntry> { it.directory }.thenBy { it.name.lowercase() })
        )
    }

    suspend fun resolveLocalUri(rootUri: Uri, relative: String): Uri? = withContext(Dispatchers.IO) {
        val root = DocumentFile.fromTreeUri(context, rootUri) ?: return@withContext null
        resolve(root, splitPath(relative))?.uri
    }

    suspend fun createFolder(rootUri: Uri, path: List<String>, name: String) = withContext(Dispatchers.IO) {
        val cleanName = name.trim().replace('/', '_').replace('\\', '_')
        require(cleanName.isNotBlank() && cleanName != "." && cleanName != "..") { "文件夹名称无效" }
        val root = requireNotNull(DocumentFile.fromTreeUri(context, rootUri)) { "无法打开手机目录" }
        val current = requireNotNull(resolve(root, path)) { "手机目录已移动或无权访问" }
        val existing = current.findFile(cleanName)
        when {
            existing == null -> requireNotNull(current.createDirectory(cleanName)) { "无法创建文件夹" }
            existing.isDirectory -> existing
            else -> error("当前位置存在同名文件")
        }
    }

    /** Create an in-place copy of a file or folder next to the original. */
    suspend fun duplicate(rootUri: Uri, entry: LocalEntry, newName: String, onProgress: (TransferState) -> Unit) = withContext(Dispatchers.IO) {
        val clean = newName.trim().replace('/', '_').replace('\\', '_')
        require(clean.isNotBlank() && clean != "." && clean != "..") { "副本名称无效" }
        val root = requireNotNull(DocumentFile.fromTreeUri(context, rootUri)) { "无法打开手机目录" }
        val source = requireNotNull(resolve(root, splitPath(entry.relative))) { "项目不存在：${entry.name}" }
        val parent = requireNotNull(resolve(root, splitPath(entry.relative).dropLast(1))) { "上级目录不存在" }
        require(parent.findFile(clean) == null) { "同级位置已有同名项目" }
        val total = if (entry.directory) countTree(source) else 1
        var done = 0
        onProgress(TransferState("创建副本", entry.name, 0, total))
        if (entry.directory) {
            val created = requireNotNull(parent.createDirectory(clean)) { "无法创建副本文件夹" }
            copyTree(source, created) {
                done++
                currentCoroutineContext().ensureActive()
                onProgress(TransferState("创建副本", "", done, total))
            }
            done = total
        } else {
            val created = requireNotNull(parent.createFile(entry.mimeType ?: "application/octet-stream", clean)) { "无法创建副本文件" }
            context.contentResolver.openInputStream(source.uri).use { input ->
                requireNotNull(input) { "无法读取：${entry.name}" }
                context.contentResolver.openOutputStream(created.uri, "w").use { output ->
                    requireNotNull(output) { "无法写入：$clean" }
                    input.copyTo(output, 1024 * 1024)
                    output.flush()
                }
            }
            done = 1
        }
        onProgress(TransferState("创建副本", completedFiles = done, totalFiles = total, completed = true, message = "副本已创建"))
    }

    private fun queryChildren(dirUri: Uri, prefix: String): List<LocalEntry>? = runCatching {
        val documentId = DocumentsContract.getDocumentId(dirUri)
        val childrenUri = DocumentsContract.buildChildDocumentsUriUsingTree(dirUri, documentId)
        val projection = arrayOf(
            DocumentsContract.Document.COLUMN_DOCUMENT_ID,
            DocumentsContract.Document.COLUMN_DISPLAY_NAME,
            DocumentsContract.Document.COLUMN_MIME_TYPE,
            DocumentsContract.Document.COLUMN_SIZE,
            DocumentsContract.Document.COLUMN_LAST_MODIFIED
        )
        val cursor = context.contentResolver.query(childrenUri, projection, null, null, null) ?: return@runCatching null
        val items = ArrayList<LocalEntry>()
        cursor.use {
            val idColumn = it.getColumnIndexOrThrow(DocumentsContract.Document.COLUMN_DOCUMENT_ID)
            val nameColumn = it.getColumnIndexOrThrow(DocumentsContract.Document.COLUMN_DISPLAY_NAME)
            val mimeColumn = it.getColumnIndexOrThrow(DocumentsContract.Document.COLUMN_MIME_TYPE)
            val sizeColumn = it.getColumnIndexOrThrow(DocumentsContract.Document.COLUMN_SIZE)
            val timeColumn = it.getColumnIndexOrThrow(DocumentsContract.Document.COLUMN_LAST_MODIFIED)
            while (it.moveToNext()) {
                val name = it.getString(nameColumn) ?: continue
                val mime = it.getString(mimeColumn).orEmpty()
                val directory = mime == DocumentsContract.Document.MIME_TYPE_DIR
                items.add(
                    LocalEntry(
                        name = name,
                        relative = listOf(prefix, name).filter(String::isNotBlank).joinToString("/"),
                        directory = directory,
                        size = if (directory) 0 else it.getLong(sizeColumn),
                        modifiedMillis = it.getLong(timeColumn),
                        mimeType = if (directory) null else mime,
                        documentUri = DocumentsContract.buildDocumentUriUsingTree(dirUri, it.getString(idColumn)).toString()
                    )
                )
            }
        }
        items
    }.getOrNull()

    private fun legacyChildren(current: DocumentFile, prefix: String): List<LocalEntry> =
        current.listFiles().asSequence()
            .filter { it.name != null }
            .map { child ->
                val name = child.name.orEmpty()
                LocalEntry(
                    name = name,
                    relative = listOf(prefix, name).filter(String::isNotBlank).joinToString("/"),
                    directory = child.isDirectory,
                    size = if (child.isFile) child.length() else 0,
                    modifiedMillis = child.lastModified(),
                    mimeType = child.type,
                    documentUri = child.uri.toString()
                )
            }
            .toList()

    suspend fun delete(
        rootUri: Uri,
        selected: List<LocalEntry>,
        onProgress: (TransferState) -> Unit
    ) = withContext(Dispatchers.IO) {
        val root = requireNotNull(DocumentFile.fromTreeUri(context, rootUri)) { "无法打开手机目录" }
        var completed = 0
        val failures = mutableListOf<String>()
        onProgress(TransferState("删除手机项目", totalFiles = selected.size))
        selected.sortedByDescending { it.relative.count { char -> char == '/' } }.forEach { entry ->
            currentCoroutineContext().ensureActive()
            runCatching {
                val target = requireNotNull(resolve(root, splitPath(entry.relative))) { "项目不存在" }
                check(target.delete()) { "删除失败" }
                check(resolve(root, splitPath(entry.relative)) == null) { "未确认删除成功" }
            }.onFailure { failures += "${entry.name}：${it.message ?: "未知错误"}" }
            completed++
            onProgress(TransferState("删除手机项目", entry.name, completed, selected.size))
        }
        if (failures.isNotEmpty()) {
            onProgress(TransferState("删除手机项目", completedFiles = completed, totalFiles = selected.size, failed = true, message = "部分删除失败"))
            error("删除未完成：${failures.size} 项失败（${failures.take(3).joinToString("；")}）")
        }
        onProgress(TransferState("删除手机项目", completedFiles = completed, totalFiles = selected.size, completed = true, message = "删除完成"))
    }

    suspend fun copy(
        rootUri: Uri,
        selected: List<LocalEntry>,
        destinationUri: Uri,
        onProgress: (TransferState) -> Unit
    ) = withContext(Dispatchers.IO) {
        val sourceRoot = requireNotNull(DocumentFile.fromTreeUri(context, rootUri)) { "无法打开手机目录" }
        val destination = requireNotNull(DocumentFile.fromTreeUri(context, destinationUri)) { "无法打开目标目录" }
        require(!destinationInsideSelection(sourceRoot, selected, destination)) { "目标目录不能与源目录相同，也不能位于所复制的文件夹内部" }
        val plan = buildPlan(sourceRoot, selected)
        val totalBytes = plan.files.values.sumOf { it.length().coerceAtLeast(0) }
        val totalItems = plan.directories.size + plan.files.size
        var completedItems = 0
        var copiedBytes = 0L
        onProgress(TransferState("复制手机文件", totalFiles = totalItems, totalBytes = totalBytes))

        plan.directories.keys.sortedBy { it.count { char -> char == '/' } }.forEach { relative ->
            ensureDirectory(destination, splitPath(relative))
            completedItems++
            onProgress(TransferState("复制手机文件", relative.substringAfterLast('/'), completedItems, totalItems, copiedBytes, totalBytes))
        }
        plan.files.forEach { (relative, source) ->
            currentCoroutineContext().ensureActive()
            val parts = splitPath(relative)
            val name = parts.last()
            val parent = ensureDirectory(destination, parts.dropLast(1))
            val existing = parent.findFile(name)
            val stagingName = ".$name.workspace-os-copy.partial"
            parent.findFile(stagingName)?.delete()
            val staging = requireNotNull(parent.createFile(source.type ?: "application/octet-stream", stagingName)) { "无法创建：$name" }
            val beforeFile = copiedBytes
            context.contentResolver.openInputStream(source.uri).use { input ->
                requireNotNull(input) { "无法读取：$name" }
                context.contentResolver.openOutputStream(staging.uri, "w").use { output ->
                    requireNotNull(output) { "无法写入：$name" }
                    val buffer = ByteArray(1024 * 1024)
                    var fileBytes = 0L
                    while (true) {
                        currentCoroutineContext().ensureActive()
                        val count = input.read(buffer)
                        if (count <= 0) break
                        output.write(buffer, 0, count)
                        fileBytes += count
                        copiedBytes = beforeFile + fileBytes
                        onProgress(TransferState("复制手机文件", name, completedItems, totalItems, copiedBytes, totalBytes))
                    }
                    output.flush()
                }
            }
            existing?.let { check(it.delete()) { "无法覆盖：$name" } }
            check(staging.renameTo(name)) { "无法提交复制文件：$name" }
            completedItems++
            copiedBytes = beforeFile + source.length().coerceAtLeast(0)
            onProgress(TransferState("复制手机文件", name, completedItems, totalItems, copiedBytes, totalBytes))
        }
        onProgress(TransferState("复制手机文件", completedFiles = totalItems, totalFiles = totalItems, copiedBytes = copiedBytes, totalBytes = totalBytes, completed = true, message = "复制完成"))
    }

    suspend fun buildUploadSelection(rootUri: Uri, selected: List<LocalEntry>): UploadSelection = withContext(Dispatchers.IO) {
        val root = requireNotNull(DocumentFile.fromTreeUri(context, rootUri)) { "无法打开手机目录" }
        val plan = buildPlan(root, selected)
        UploadSelection(
            directories = plan.directories.keys.toList(),
            files = plan.files.map { (relative, document) ->
                LocalDocument(document.uri, document.name ?: relative.substringAfterLast('/'), document.length(), relative)
            }
        )
    }

    /** Rename a local file or folder in place. */
    suspend fun rename(rootUri: Uri, entry: LocalEntry, newName: String, onProgress: (TransferState) -> Unit) = withContext(Dispatchers.IO) {
        val clean = newName.trim().replace('/', '_').replace('\\', '_')
        require(clean.isNotBlank() && clean != "." && clean != "..") { "名称无效" }
        require(clean != entry.name) { "新旧名称相同" }
        val root = requireNotNull(DocumentFile.fromTreeUri(context, rootUri)) { "无法打开手机目录" }
        val target = requireNotNull(resolve(root, splitPath(entry.relative))) { "项目不存在：${entry.name}" }
        val parent = requireNotNull(resolve(root, splitPath(entry.relative).dropLast(1))) { "上级目录不存在" }
        require(parent.findFile(clean) == null) { "同级位置已有同名项目" }
        onProgress(TransferState("重命名", entry.name))
        check(target.renameTo(clean)) { "系统不允许重命名：${entry.name}" }
        check(resolve(root, splitPath(entry.relative).dropLast(1) + clean) != null) { "未确认重命名成功" }
        onProgress(TransferState("重命名", clean, completedFiles = 1, totalFiles = 1, completed = true, message = "重命名完成"))
    }

    private fun buildPlan(root: DocumentFile, selected: List<LocalEntry>): LocalPlan {
        val plan = LocalPlan()
        fun visit(document: DocumentFile, relative: String) {
            if (document.isDirectory) {
                plan.directories[relative] = document
                document.listFiles().forEach { child ->
                    val name = child.name ?: return@forEach
                    visit(child, "$relative/$name")
                }
            } else if (document.isFile) {
                plan.files[relative] = document
            }
        }
        selected.forEach { entry ->
            val document = requireNotNull(resolve(root, splitPath(entry.relative))) { "项目不存在：${entry.name}" }
            visit(document, entry.name)
        }
        return plan
    }

    private fun resolve(root: DocumentFile, path: List<String>): DocumentFile? {
        var current: DocumentFile = root
        path.forEach { name -> current = current.findFile(name) ?: return null }
        return current
    }

    private fun ensureDirectory(root: DocumentFile, path: List<String>): DocumentFile {
        var current = root
        path.forEach { name ->
            val existing = current.findFile(name)
            current = when {
                existing == null -> requireNotNull(current.createDirectory(name)) { "无法创建文件夹：$name" }
                existing.isDirectory -> existing
                else -> error("目标位置存在同名文件：$name")
            }
        }
        return current
    }

    private fun countTree(document: DocumentFile): Int = document.listFiles().sumOf { child ->
        if (child.isDirectory) 1 + countTree(child) else 1
    }

    private suspend fun copyTree(source: DocumentFile, target: DocumentFile, onItem: suspend () -> Unit) {
        currentCoroutineContext().ensureActive()
        source.listFiles().forEach { child ->
            val name = child.name ?: return@forEach
            currentCoroutineContext().ensureActive()
            if (child.isDirectory) {
                val existing = target.findFile(name)
                val created = when {
                    existing == null -> requireNotNull(target.createDirectory(name)) { "无法创建文件夹：$name" }
                    existing.isDirectory -> existing
                    else -> error("目标存在同名文件：$name")
                }
                onItem()
                copyTree(child, created, onItem)
            } else {
                target.findFile(name)?.delete()
                val created = requireNotNull(target.createFile(child.type ?: "application/octet-stream", name)) { "无法创建：$name" }
                context.contentResolver.openInputStream(child.uri).use { input ->
                    requireNotNull(input) { "无法读取：$name" }
                    context.contentResolver.openOutputStream(created.uri, "w").use { output ->
                        requireNotNull(output) { "无法写入：$name" }
                        input.copyTo(output, 1024 * 1024)
                        output.flush()
                    }
                }
                onItem()
            }
        }
    }

    private fun destinationInsideSelection(root: DocumentFile, selected: List<LocalEntry>, destination: DocumentFile): Boolean {
        val destinationId = runCatching { DocumentsContract.getDocumentId(destination.uri) }.getOrNull() ?: return false
        val sourceParentPath = selected.firstOrNull()?.relative?.let(::splitPath)?.dropLast(1).orEmpty()
        val sourceParentId = resolve(root, sourceParentPath)?.uri?.let {
            runCatching { DocumentsContract.getDocumentId(it) }.getOrNull()
        }
        if (destinationId == sourceParentId) return true
        return selected.filter { it.directory }.any { entry ->
            val source = resolve(root, splitPath(entry.relative)) ?: return@any false
            val sourceId = runCatching { DocumentsContract.getDocumentId(source.uri) }.getOrNull() ?: return@any false
            destinationId == sourceId || destinationId.startsWith("$sourceId/")
        }
    }

    private fun splitPath(path: String): List<String> = path.split('/').filter(String::isNotBlank)
}
