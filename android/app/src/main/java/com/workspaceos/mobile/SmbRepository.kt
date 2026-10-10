package com.workspaceos.mobile

import android.content.ContentUris
import android.content.ContentValues
import android.content.Context
import android.net.Uri
import android.os.Build
import android.os.Environment
import android.os.StatFs
import android.provider.MediaStore
import android.provider.OpenableColumns
import com.hierynomus.msdtyp.AccessMask
import com.hierynomus.msfscc.FileAttributes
import com.hierynomus.mssmb2.SMB2CreateDisposition
import com.hierynomus.mssmb2.SMB2CreateOptions
import com.hierynomus.mssmb2.SMB2ShareAccess
import com.hierynomus.smbj.SMBClient
import com.hierynomus.smbj.auth.AuthenticationContext
import com.hierynomus.smbj.share.DiskShare
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.currentCoroutineContext
import kotlinx.coroutines.ensureActive
import kotlinx.coroutines.withContext
import java.io.File
import java.io.FileOutputStream
import java.nio.charset.StandardCharsets

data class RemoteEntry(
    val name: String,
    val relative: String,
    val directory: Boolean,
    val size: Long,
    val modifiedMillis: Long
)

data class StorageInfo(val totalBytes: Long = 0, val freeBytes: Long = 0) {
    val usedBytes: Long get() = (totalBytes - freeBytes).coerceAtLeast(0)
    val usedFraction: Float get() = if (totalBytes > 0) usedBytes.toFloat() / totalBytes else 0f
}

data class BrowseResult(val entries: List<RemoteEntry>, val nasStorage: StorageInfo, val phoneStorage: StorageInfo)

data class LocalDocument(val uri: Uri, val name: String, val size: Long, val relativePath: String = name)

/** Where a NAS download is committed on the phone. */
sealed class DownloadTarget {
    /** MediaStore Downloads with a relative sub-folder, e.g. Download/WorkspaceOS. */
    data class DownloadsFolder(val subDir: String) : DownloadTarget()

    /** A user-picked SAF tree; folder hierarchy is mirrored inside it. */
    data class Tree(val rootUri: Uri) : DownloadTarget()
}

data class TransferState(
    val title: String,
    val currentFile: String = "",
    val completedFiles: Int = 0,
    val totalFiles: Int = 0,
    val copiedBytes: Long = 0,
    val totalBytes: Long = 0,
    val completed: Boolean = false,
    val failed: Boolean = false,
    val message: String = ""
) {
    val fraction: Float
        get() = when {
            completed -> 1f
            totalBytes > 0 -> (copiedBytes.toDouble() / totalBytes).toFloat().coerceIn(0f, 1f)
            totalFiles > 0 -> (completedFiles.toFloat() / totalFiles).coerceIn(0f, 1f)
            else -> 0f
        }
}

/** A file that has just been published on the phone and can be opened in place. */
data class SyncedFile(val name: String, val relative: String, val size: Long, val uri: Uri)

class SmbRepository(private val context: Context) {
    fun phoneStorageInfo(): StorageInfo = phoneStorage()

    /** Append one JSONL sync record to the canonical NAS .log. */
    suspend fun appendSyncLog(config: NasEndpoint, direction: String, mode: String, files: List<String>) = withContext(Dispatchers.IO) {
        withShare(config) { disk ->
            val now = java.time.ZonedDateTime.now()
            val day = now.toLocalDate().toString()
            val path = "09_System/SystemLog/WorkspaceOS/sync-$day.log"
            ensureRemoteDirectory(disk, "09_System/SystemLog/WorkspaceOS")
            val access = setOf(AccessMask.GENERIC_READ, AccessMask.GENERIC_WRITE)
            val sharing = setOf(SMB2ShareAccess.FILE_SHARE_READ, SMB2ShareAccess.FILE_SHARE_WRITE, SMB2ShareAccess.FILE_SHARE_DELETE)
            disk.openFile(path, access, setOf(FileAttributes.FILE_ATTRIBUTE_NORMAL), sharing, SMB2CreateDisposition.FILE_OPEN_IF,
                setOf(SMB2CreateOptions.FILE_NON_DIRECTORY_FILE)).use { remote ->
                val label = if (mode == "overwrite") "覆盖" else "同步"
                val verb = if (direction == "to_nas") "上传到 NAS" else "下载到手机"
                val escaped = files.joinToString(",") { "\"" + it.replace("\\", "\\\\").replace("\"", "\\\"") + "\"" }
                val text = "{\"timestamp\":\"$now\",\"operation\":\"sync\",\"direction\":\"$verb\",\"mode\":\"$label\",\"file_count\":${files.size},\"files\":[$escaped]}\n"
                val offset = remote.fileInformation.standardInformation.endOfFile
                val bytes = text.toByteArray(StandardCharsets.UTF_8)
                remote.write(bytes, offset, 0, bytes.size)
                remote.flush()
            }
        }
    }

    private suspend fun <T> withShare(config: NasEndpoint, block: suspend (DiskShare) -> T): T {
        SMBClient().use { client ->
            client.connect(config.host.trim()).use { connection ->
                connection.authenticate(AuthenticationContext(config.username, config.password.toCharArray(), "")).use { session ->
                    (session.connectShare(config.share.trim()) as DiskShare).use { disk -> return block(disk) }
                }
            }
        }
    }

    suspend fun browse(config: NasEndpoint, path: String): BrowseResult = withContext(Dispatchers.IO) {
        withShare(config) { disk ->
            val entries = listDirectory(disk, normalize(path))
            val share = disk.shareInformation
            BrowseResult(entries, StorageInfo(share.totalSpace, share.freeSpace), phoneStorage())
        }
    }

    suspend fun createFolder(config: NasEndpoint, parent: String, name: String) = withContext(Dispatchers.IO) {
        val cleanName = name.trim().replace('\\', '_').replace('/', '_')
        require(cleanName.isNotBlank() && cleanName != "." && cleanName != "..") { "文件夹名称无效" }
        withShare(config) { disk ->
            val target = joinRemote(parent, cleanName)
            if (!disk.folderExists(target)) disk.mkdir(target)
            check(disk.folderExists(target)) { "NAS 未确认文件夹创建成功" }
        }
    }

    /** Rename a remote file or folder in place (same directory). */
    suspend fun renameRemote(config: NasEndpoint, entry: RemoteEntry, newName: String) = withContext(Dispatchers.IO) {
        val clean = newName.trim().replace('\\', '_').replace('/', '_')
        require(clean.isNotBlank() && clean != "." && clean != "..") { "名称无效" }
        withShare(config) { disk ->
            val parent = normalize(entry.relative).substringBeforeLast('/', "")
            val target = joinRemote(parent, clean)
            check(target != entry.relative) { "新旧名称相同" }
            check(!disk.fileExists(target) && !disk.folderExists(target)) { "已存在同名项目：$clean" }
            val access = setOf(AccessMask.GENERIC_READ, AccessMask.DELETE)
            val sharing = setOf(SMB2ShareAccess.FILE_SHARE_READ, SMB2ShareAccess.FILE_SHARE_WRITE, SMB2ShareAccess.FILE_SHARE_DELETE)
            if (entry.directory) {
                disk.openDirectory(entry.relative, access, setOf(FileAttributes.FILE_ATTRIBUTE_DIRECTORY), sharing, SMB2CreateDisposition.FILE_OPEN, null)
                    .use { dir -> dir.rename(target, false) }
                check(disk.folderExists(target)) { "NAS 未确认重命名成功" }
            } else {
                disk.openFile(entry.relative, access, setOf(FileAttributes.FILE_ATTRIBUTE_NORMAL), sharing, SMB2CreateDisposition.FILE_OPEN, setOf(SMB2CreateOptions.FILE_NON_DIRECTORY_FILE))
                    .use { file -> file.rename(target, false) }
                check(disk.fileExists(target)) { "NAS 未确认重命名成功" }
            }
        }
    }

    suspend fun deleteRemote(
        config: NasEndpoint,
        selected: List<RemoteEntry>,
        onProgress: (TransferState) -> Unit
    ) = withContext(Dispatchers.IO) {
        var completed = 0
        onProgress(TransferState("删除 NAS 项目", totalFiles = selected.size))
        withShare(config) { disk ->
            selected.sortedByDescending { it.relative.count { char -> char == '/' } }.forEach { entry ->
                currentCoroutineContext().ensureActive()
                if (entry.directory) disk.rmdir(entry.relative, true) else disk.rm(entry.relative)
                check(!disk.folderExists(entry.relative) && !disk.fileExists(entry.relative)) { "未确认删除成功：${entry.name}" }
                completed++
                onProgress(TransferState("删除 NAS 项目", entry.name, completed, selected.size))
            }
        }
        onProgress(TransferState("删除 NAS 项目", completedFiles = completed, totalFiles = selected.size, completed = true, message = "删除完成"))
    }

    /** Stream one remote file into a local target file (used for quick preview). */
    suspend fun downloadTo(config: NasEndpoint, entry: RemoteEntry, target: File) = withContext(Dispatchers.IO) {
        withShare(config) { disk ->
            disk.openFile(
                entry.relative,
                setOf(AccessMask.GENERIC_READ),
                null,
                setOf(SMB2ShareAccess.FILE_SHARE_READ),
                SMB2CreateDisposition.FILE_OPEN,
                setOf(SMB2CreateOptions.FILE_NON_DIRECTORY_FILE)
            ).use { remote ->
                val total = remote.fileInformation.standardInformation.endOfFile
                FileOutputStream(target).use { output ->
                    val buffer = ByteArray(1024 * 1024)
                    var offset = 0L
                    while (offset < total) {
                        currentCoroutineContext().ensureActive()
                        val requested = minOf(buffer.size.toLong(), total - offset).toInt()
                        val read = remote.read(buffer, offset, 0, requested)
                        if (read <= 0) break
                        output.write(buffer, 0, read)
                        offset += read
                    }
                    output.flush()
                    check(offset == total) { "预览下载不完整：${entry.name}" }
                }
            }
        }
    }

    suspend fun describeDocuments(uris: List<Uri>): UploadSelection = withContext(Dispatchers.IO) {
        val files = uris.distinct().mapNotNull { uri ->
            var name: String? = null
            var size = -1L
            context.contentResolver.query(uri, arrayOf(OpenableColumns.DISPLAY_NAME, OpenableColumns.SIZE), null, null, null)?.use { cursor ->
                if (cursor.moveToFirst()) {
                    name = cursor.getString(0)
                    if (!cursor.isNull(1)) size = cursor.getLong(1)
                }
            }
            val safeName = (name ?: uri.lastPathSegment ?: "mobile-file").substringAfterLast('/').replace('\\', '_')
            LocalDocument(uri, safeName, size)
        }
        UploadSelection(files = files)
    }

    suspend fun upload(
        config: NasEndpoint,
        parent: String,
        selection: UploadSelection,
        onProgress: (TransferState) -> Unit
    ) = withContext(Dispatchers.IO) {
        val documents = selection.files
        val knownTotal = documents.sumOf { it.size.coerceAtLeast(0) }
        var copiedTotal = 0L
        var completedItems = 0
        val totalItems = selection.directories.size + documents.size
        onProgress(TransferState("上传到 NAS", totalFiles = totalItems, totalBytes = knownTotal))
        withShare(config) { disk ->
            selection.directories.sortedBy { it.count { char -> char == '/' } }.forEach { relative ->
                val target = joinRemote(parent, relative)
                ensureRemoteDirectory(disk, target)
                completedItems++
                onProgress(TransferState("上传到 NAS", relative.substringAfterLast('/'), completedItems, totalItems, copiedTotal, knownTotal))
            }
            documents.forEach { document ->
                currentCoroutineContext().ensureActive()
                val target = joinRemote(parent, document.relativePath)
                ensureRemoteDirectory(disk, target.substringBeforeLast('/', ""))
                val staging = "$target.workspace-os-upload.partial"
                val access = setOf(AccessMask.GENERIC_READ, AccessMask.GENERIC_WRITE, AccessMask.DELETE)
                val sharing = setOf(SMB2ShareAccess.FILE_SHARE_READ, SMB2ShareAccess.FILE_SHARE_WRITE, SMB2ShareAccess.FILE_SHARE_DELETE)
                val options = setOf(SMB2CreateOptions.FILE_NON_DIRECTORY_FILE)
                disk.openFile(staging, access, setOf(FileAttributes.FILE_ATTRIBUTE_NORMAL), sharing, SMB2CreateDisposition.FILE_OPEN_IF, options).use { remote ->
                    var offset = remote.fileInformation.standardInformation.endOfFile
                    if (document.size >= 0 && offset > document.size) {
                        remote.setLength(0)
                        offset = 0
                    }
                    val beforeFile = copiedTotal
                    context.contentResolver.openInputStream(document.uri).use { input ->
                        requireNotNull(input) { "无法读取手机文件：${document.name}" }
                        var skipped = 0L
                        while (skipped < offset) {
                            val value = input.skip(offset - skipped)
                            if (value <= 0) break
                            skipped += value
                        }
                        if (skipped < offset) {
                            remote.setLength(0)
                            offset = 0
                        }
                        val buffer = ByteArray(1024 * 1024)
                        var read: Int
                        while (input.read(buffer).also { read = it } > 0) {
                            currentCoroutineContext().ensureActive()
                            remote.write(buffer, offset, 0, read)
                            offset += read
                            copiedTotal = beforeFile + offset
                            onProgress(TransferState("上传到 NAS", document.name, completedItems, totalItems, copiedTotal, knownTotal))
                        }
                    }
                    remote.flush()
                    if (document.size >= 0) remote.setLength(document.size)
                    remote.rename(target, true)
                }
                check(disk.fileExists(target)) { "NAS 未确认文件上传成功：${document.name}" }
                if (document.size >= 0) {
                    val committedSize = disk.getFileInformation(target).standardInformation.endOfFile
                    check(committedSize == document.size) { "NAS 文件大小校验失败：${document.name}" }
                }
                completedItems++
                copiedTotal = if (document.size >= 0) copiedTotal.coerceAtLeast(documents.take(completedItems - selection.directories.size).sumOf { it.size.coerceAtLeast(0) }) else copiedTotal
                onProgress(TransferState("上传到 NAS", document.name, completedItems, totalItems, copiedTotal, knownTotal))
            }
        }
        onProgress(TransferState("上传到 NAS", completedFiles = totalItems, totalFiles = totalItems, copiedBytes = copiedTotal, totalBytes = knownTotal, completed = true, message = "上传完成"))
    }

    suspend fun download(
        config: NasEndpoint,
        selected: List<RemoteEntry>,
        target: DownloadTarget,
        onProgress: (TransferState) -> Unit
    ): List<SyncedFile> = withContext(Dispatchers.IO) {
        val published = mutableListOf<SyncedFile>()
        withShare(config) { disk ->
            val files = collectRemoteFiles(disk, selected)
            val totalBytes = files.sumOf { it.size.coerceAtLeast(0) }
            var copiedTotal = 0L
            var completedFiles = 0
            onProgress(TransferState("同步到手机", totalFiles = files.size, totalBytes = totalBytes))
            files.forEach { entry ->
                currentCoroutineContext().ensureActive()
                val partialRoot = File(context.cacheDir, "workspaceos-downloads").apply { mkdirs() }
                val partial = File(partialRoot, "${entry.relative.hashCode()}-${entry.name}.partial")
                disk.openFile(
                    entry.relative,
                    setOf(AccessMask.GENERIC_READ),
                    null,
                    setOf(SMB2ShareAccess.FILE_SHARE_READ),
                    SMB2CreateDisposition.FILE_OPEN,
                    setOf(SMB2CreateOptions.FILE_NON_DIRECTORY_FILE)
                ).use { remote ->
                    val total = remote.fileInformation.standardInformation.endOfFile
                    var offset = partial.takeIf { it.exists() }?.length() ?: 0L
                    if (offset > total) { partial.delete(); offset = 0 }
                    val beforeFile = copiedTotal
                    FileOutputStream(partial, offset > 0).use { output ->
                        val buffer = ByteArray(1024 * 1024)
                        while (offset < total) {
                            currentCoroutineContext().ensureActive()
                            val requested = minOf(buffer.size.toLong(), total - offset).toInt()
                            val read = remote.read(buffer, offset, 0, requested)
                            if (read <= 0) break
                            output.write(buffer, 0, read)
                            offset += read
                            copiedTotal = beforeFile + offset
                            onProgress(TransferState("同步到手机", entry.name, completedFiles, files.size, copiedTotal, totalBytes))
                        }
                    }
                    check(offset == total) { "文件下载不完整：${entry.name}" }
                }
                val publishedUri = when (target) {
                    is DownloadTarget.Tree -> publishDownloadToTree(partial, entry.relative, target.rootUri)
                    is DownloadTarget.DownloadsFolder -> publishDownload(partial, entry.relative, target.subDir)
                }
                published += SyncedFile(entry.name, entry.relative, entry.size, publishedUri)
                completedFiles++
                copiedTotal = files.take(completedFiles).sumOf { it.size.coerceAtLeast(0) }
                onProgress(TransferState("同步到手机", entry.name, completedFiles, files.size, copiedTotal, totalBytes))
            }
            onProgress(TransferState("同步到手机", completedFiles = completedFiles, totalFiles = files.size, copiedBytes = copiedTotal, totalBytes = totalBytes, completed = true, message = "同步完成"))
        }
        published
    }

    private fun publishDownloadToTree(partial: File, relative: String, rootUri: Uri): Uri {
        androidx.documentfile.provider.DocumentFile.fromTreeUri(context, rootUri).also {
            requireNotNull(it) { "无法打开所选下载目录" }
        }
        val fileName = relative.substringAfterLast('/')
        val parts = relative.substringBeforeLast('/', "").trim('/').split('/').filter(String::isNotBlank)
        var dir = androidx.documentfile.provider.DocumentFile.fromTreeUri(context, rootUri)!!
        parts.forEach { part ->
            val existing = dir.findFile(part)
            dir = when {
                existing == null -> requireNotNull(dir.createDirectory(part)) { "无法创建文件夹：$part" }
                existing.isDirectory -> existing
                else -> error("下载目录中存在同名文件：$part")
            }
        }
        dir.findFile(fileName)?.delete()
        val created = requireNotNull(dir.createFile("*/*", fileName)) { "无法创建：$fileName" }
        context.contentResolver.openOutputStream(created.uri, "w").use { output ->
            requireNotNull(output) { "无法写入：$fileName" }
            partial.inputStream().use { input -> input.copyTo(output, 1024 * 1024) }
            output.flush()
        }
        partial.delete()
        return created.uri
    }

    private fun collectRemoteFiles(disk: DiskShare, selected: List<RemoteEntry>): List<RemoteEntry> {
        val result = linkedMapOf<String, RemoteEntry>()
        fun add(entry: RemoteEntry) {
            if (!entry.directory) {
                result[entry.relative] = entry
                return
            }
            listDirectory(disk, entry.relative).forEach(::add)
        }
        selected.forEach(::add)
        return result.values.toList()
    }

    private fun ensureRemoteDirectory(disk: DiskShare, path: String) {
        var current = ""
        normalize(path).split('/').filter(String::isNotBlank).forEach { part ->
            current = joinRemote(current, part)
            when {
                disk.folderExists(current) -> Unit
                disk.fileExists(current) -> error("NAS 存在同名文件：$current")
                else -> disk.mkdir(current)
            }
        }
    }

    private fun listDirectory(disk: DiskShare, path: String): List<RemoteEntry> = disk.list(path).asSequence()
        .filterNot { it.fileName == "." || it.fileName == ".." }
        .map {
            val directory = (it.fileAttributes and FileAttributes.FILE_ATTRIBUTE_DIRECTORY.value) != 0L
            RemoteEntry(it.fileName, joinRemote(path, it.fileName), directory, if (directory) 0 else it.endOfFile, it.lastWriteTime.toEpochMillis())
        }
        .sortedWith(compareByDescending<RemoteEntry> { it.directory }.thenBy { it.name.lowercase() })
        .toList()

    private fun phoneStorage(): StorageInfo {
        val stats = StatFs(Environment.getExternalStorageDirectory().absolutePath)
        return StorageInfo(stats.totalBytes, stats.availableBytes)
    }

    private fun publishDownload(partial: File, relative: String, downloadDir: String): Uri {
        val fileName = relative.substringAfterLast('/')
        val parent = relative.substringBeforeLast('/', "").trim('/')
        val folder = downloadDir.trim().trim('/').replace('\\', '/').ifBlank { "WorkspaceOS" }
        if (Build.VERSION.SDK_INT < Build.VERSION_CODES.Q) {
            val root = File(context.getExternalFilesDir(Environment.DIRECTORY_DOWNLOADS), "$folder/$parent")
            root.mkdirs()
            val target = File(root, fileName)
            if (target.exists()) target.delete()
            check(partial.renameTo(target)) { "无法提交下载文件" }
            return Uri.fromFile(target)
        }

        val resolver = context.contentResolver
        val collection = MediaStore.Downloads.EXTERNAL_CONTENT_URI
        val relativePath = "${Environment.DIRECTORY_DOWNLOADS}/$folder/${if (parent.isBlank()) "" else "$parent/"}"
        resolver.query(
            collection,
            arrayOf(MediaStore.Downloads._ID),
            "${MediaStore.Downloads.DISPLAY_NAME}=? AND ${MediaStore.Downloads.RELATIVE_PATH}=?",
            arrayOf(fileName, relativePath),
            null
        )?.use { cursor ->
            while (cursor.moveToNext()) resolver.delete(ContentUris.withAppendedId(collection, cursor.getLong(0)), null, null)
        }
        val values = ContentValues().apply {
            put(MediaStore.Downloads.DISPLAY_NAME, fileName)
            put(MediaStore.Downloads.RELATIVE_PATH, relativePath)
            put(MediaStore.Downloads.IS_PENDING, 1)
        }
        val uri = checkNotNull(resolver.insert(collection, values)) { "无法创建下载文件" }
        try {
            checkNotNull(resolver.openOutputStream(uri, "w")).use { output -> partial.inputStream().use { it.copyTo(output) } }
            resolver.update(uri, ContentValues().apply { put(MediaStore.Downloads.IS_PENDING, 0) }, null, null)
            partial.delete()
        } catch (error: Throwable) {
            resolver.delete(uri, null, null)
            throw error
        }
        return uri
    }

    private fun normalize(path: String): String = path.replace('\\', '/').trim('/').also {
        require(it.split('/').none { part -> part == ".." }) { "路径无效" }
    }

    private fun joinRemote(parent: String, name: String): String = listOf(normalize(parent), name.trim('/')).filter(String::isNotBlank).joinToString("/")
}
