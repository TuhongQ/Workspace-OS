package com.workspaceos.mobile

import android.os.Bundle
import androidx.activity.ComponentActivity
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.compose.setContent
import androidx.activity.result.contract.ActivityResultContracts
import androidx.activity.viewModels
import androidx.compose.animation.AnimatedVisibility
import androidx.compose.animation.fadeIn
import androidx.compose.animation.fadeOut
import androidx.compose.animation.slideInVertically
import androidx.compose.foundation.Canvas
import androidx.compose.foundation.Image
import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.gestures.detectTransformGestures
import androidx.compose.foundation.horizontalScroll
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.ColumnScope
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.RowScope
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.navigationBarsPadding
import androidx.compose.foundation.layout.offset
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.statusBarsPadding
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.Button
import androidx.compose.material3.ButtonDefaults
import androidx.compose.material3.Checkbox
import androidx.compose.material3.CheckboxDefaults
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.DropdownMenu
import androidx.compose.material3.DropdownMenuItem
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.LinearProgressIndicator
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.OutlinedTextFieldDefaults
import androidx.compose.material3.Scaffold
import androidx.compose.material3.Surface
import androidx.compose.material3.SwipeToDismissBox
import androidx.compose.material3.SwipeToDismissBoxValue
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.material3.Typography
import androidx.compose.material3.darkColorScheme
import androidx.compose.material3.rememberSwipeToDismissBoxState
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Brush
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.Path
import androidx.compose.ui.graphics.StrokeCap
import androidx.compose.ui.graphics.StrokeJoin
import androidx.compose.ui.graphics.asImageBitmap
import androidx.compose.ui.graphics.drawscope.Stroke
import androidx.compose.ui.graphics.graphicsLayer
import androidx.compose.ui.input.pointer.pointerInput
import androidx.compose.ui.layout.ContentScale
import androidx.compose.ui.platform.LocalConfiguration
import androidx.compose.ui.platform.LocalDensity
import androidx.compose.ui.text.AnnotatedString
import androidx.compose.ui.text.SpanStyle
import androidx.compose.ui.text.buildAnnotatedString
import androidx.compose.ui.text.font.FontFamily
import androidx.compose.ui.text.font.FontStyle
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.input.PasswordVisualTransformation
import androidx.compose.ui.text.input.VisualTransformation
import androidx.compose.ui.text.style.TextDecoration
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.text.withStyle
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.compose.ui.window.Dialog
import androidx.compose.ui.window.DialogProperties
import androidx.core.view.WindowCompat
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import kotlinx.coroutines.launch
import kotlinx.coroutines.delay
import android.graphics.BitmapFactory
import android.net.Uri
import java.text.SimpleDateFormat
import java.util.Date
import java.util.Locale
import kotlin.math.roundToInt

private val Background = Color(0xFF050816)
private val Panel = Color(0xE6121A34)
private val PanelSoft = Color(0xB2182445)
private val Line = Color(0x4D6A80BE)
private val Accent = Color(0xFF7C5CFF)
private val Cyan = Color(0xFF21D4FD)
private val Green = Color(0xFF42E6A4)
private val Warning = Color(0xFFFFD166)
private val Danger = Color(0xFFFF5F7E)
private val Ink = Color(0xFFF1F5FF)
private val Muted = Color(0xFF9AA9C8)
private val CardShape = RoundedCornerShape(22.dp)

class MainActivity : ComponentActivity() {
    private val workspaceViewModel by viewModels<WorkspaceViewModel> { WorkspaceViewModel.Factory(application) }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        WindowCompat.setDecorFitsSystemWindows(window, false)
        setContent { WorkspaceTheme { WorkspaceOSApp(workspaceViewModel) } }
    }
}

@Composable
private fun WorkspaceTheme(content: @Composable () -> Unit) {
    val colors = darkColorScheme(
        primary = Accent,
        secondary = Cyan,
        tertiary = Green,
        background = Background,
        surface = Panel,
        onPrimary = Color.White,
        onBackground = Ink,
        onSurface = Ink,
        error = Danger
    )
    MaterialTheme(colorScheme = colors, typography = Typography(), content = content)
}

@OptIn(ExperimentalMaterial3Api::class)
@Composable
private fun WorkspaceOSApp(viewModel: WorkspaceViewModel) {
    val state by viewModel.state.collectAsStateWithLifecycle()
    var createFolderFor by remember { mutableStateOf<WorkspacePage?>(null) }
    var remoteDeleteTargets by remember { mutableStateOf<List<RemoteEntry>>(emptyList()) }
    var localDeleteTargets by remember { mutableStateOf<List<LocalEntry>>(emptyList()) }
    var renameRemoteTarget by remember { mutableStateOf<RemoteEntry?>(null) }
    var renameLocalTarget by remember { mutableStateOf<LocalEntry?>(null) }
    var duplicateTarget by remember { mutableStateOf<LocalEntry?>(null) }
    var editProfile by remember { mutableStateOf<Boolean>(false) }
    var settingsOpen by remember { mutableStateOf<Boolean>(false) }

    val uploadLauncher = rememberLauncherForActivityResult(ActivityResultContracts.OpenMultipleDocuments()) { uris ->
        viewModel.uploadUris(uris)
    }
    val phoneRootLauncher = rememberLauncherForActivityResult(ActivityResultContracts.OpenDocumentTree()) { uri ->
        if (uri != null) viewModel.chooseLocalRoot(uri)
    }
    val copyDestinationLauncher = rememberLauncherForActivityResult(ActivityResultContracts.OpenDocumentTree()) { uri ->
        if (uri != null) viewModel.copyLocalSelected(uri)
    }
    val downloadTreeLauncher = rememberLauncherForActivityResult(ActivityResultContracts.OpenDocumentTree()) { uri ->
        if (uri != null) viewModel.setDownloadTree(uri)
    }

    val filteredRemote = remember(state.entries, state.search) {
        val query = state.search.trim()
        if (query.isBlank()) state.entries else state.entries.filter { it.name.contains(query, ignoreCase = true) }
    }
    val filteredLocal = remember(state.localEntries, state.localSearch) {
        val query = state.localSearch.trim()
        if (query.isBlank()) state.localEntries else state.localEntries.filter { it.name.contains(query, ignoreCase = true) }
    }

    Box(
        Modifier.fillMaxSize().background(
            Brush.linearGradient(
                listOf(Color(0xFF050816), Color(0xFF08142D), Color(0xFF101232), Color(0xFF050816))
            )
        )
    ) {
        Box(
            Modifier.size(330.dp).offset(x = (-150).dp, y = 40.dp)
                .background(Brush.radialGradient(listOf(Color(0x4432C7FF), Color.Transparent)), CircleShape)
        )
        Box(
            Modifier.size(390.dp).offset(x = 190.dp, y = (-100).dp)
                .background(Brush.radialGradient(listOf(Color(0x557C5CFF), Color.Transparent)), CircleShape)
        )
        Scaffold(
            containerColor = Color.Transparent,
            bottomBar = { state.task?.let { TaskCenter(it, viewModel::clearTask, viewModel::cancelTask) } }
        ) { padding ->
            LazyColumn(
                modifier = Modifier.fillMaxSize().statusBarsPadding(),
                contentPadding = PaddingValues(
                    start = 16.dp,
                    end = 16.dp,
                    top = 10.dp,
                    bottom = padding.calculateBottomPadding() + 18.dp
                ),
                verticalArrangement = Arrangement.spacedBy(12.dp)
            ) {
                item { HeroHeader(state) { settingsOpen = true } }
                item {
                    ProfileBar(
                        state = state,
                        onSwitch = viewModel::switchProfile,
                        onAdd = viewModel::addProfile,
                        onEdit = { editProfile = true }
                    )
                }
                item { AnimatedConnectionCard(state, viewModel::updateConfig, viewModel::connect) }
                item { StorageOverview(state.nasStorage, state.phoneStorage, state.connected) }
                item { PageSwitcher(state.page, viewModel::setPage) }

                if (state.page == WorkspacePage.NAS) {
                    if (state.recentSynced.isNotEmpty()) {
                        item { RecentSyncedPanel(state.recentSynced, viewModel::openSynced, viewModel::clearRecentSynced) }
                    }
                    item {
                        NasToolbar(
                            state = state,
                            onSearch = viewModel::setSearch,
                            onUp = viewModel::up,
                            onRoot = viewModel::goRoot,
                            onRefresh = viewModel::refresh,
                            onUpload = { uploadLauncher.launch(arrayOf("*/*")) },
                            onCreateFolder = { createFolderFor = WorkspacePage.NAS },
                            onSync = viewModel::syncSelected,
                            onSelectAll = viewModel::selectAllVisible,
                            onDelete = {
                                remoteDeleteTargets = state.entries.filter { it.relative in state.selected }
                            },
                            onSort = viewModel::setSort
                        )
                    }
                    when {
                        !state.connected -> item { EmptyPanel("连接 NAS 后，这里会显示 Workspace 目录") }
                        filteredRemote.isEmpty() -> item { EmptyPanel(if (state.search.isBlank()) "这个 NAS 文件夹是空的" else "没有匹配的 NAS 文件") }
                        else -> items(filteredRemote, key = { it.relative }) { entry ->
                            RemoteEntryRow(
                                entry = entry,
                                selected = entry.relative in state.selected,
                                onToggle = { viewModel.toggleSelected(entry) },
                                onOpen = { viewModel.open(entry) },
                                onPreview = { viewModel.openRemote(entry) },
                                onDownload = { viewModel.download(entry) },
                                onRename = { renameRemoteTarget = entry },
                                onDeleteRequested = { remoteDeleteTargets = listOf(entry) }
                            )
                        }
                    }
                } else {
                    item {
                        PhoneToolbar(
                            state = state,
                            onChooseRoot = { phoneRootLauncher.launch(null) },
                            onSearch = viewModel::setLocalSearch,
                            onUp = viewModel::localUp,
                            onRoot = viewModel::goLocalRoot,
                            onRefresh = viewModel::refreshLocal,
                            onSelectAll = viewModel::selectAllLocal,
                            onCreateFolder = { createFolderFor = WorkspacePage.PHONE },
                            onCopy = { copyDestinationLauncher.launch(null) },
                            onDelete = {
                                localDeleteTargets = state.localEntries.filter { it.relative in state.localSelected }
                            },
                            onUpload = viewModel::uploadLocalSelected,
                            onSort = viewModel::setSort
                        )
                    }
                    when {
                        state.localRootUri == null -> item { EmptyPanel("点击“选择手机目录”，授权后即可查看和管理手机文件") }
                        filteredLocal.isEmpty() -> item { EmptyPanel(if (state.localSearch.isBlank()) "这个手机文件夹是空的" else "没有匹配的手机文件") }
                        else -> items(filteredLocal, key = { it.relative }) { entry ->
                            LocalEntryRow(
                                entry = entry,
                                selected = entry.relative in state.localSelected,
                                onToggle = { viewModel.toggleLocalSelected(entry) },
                                onOpen = { viewModel.openLocal(entry) },
                                onRename = { renameLocalTarget = entry },
                                onDuplicate = { duplicateTarget = entry },
                                onDeleteRequested = { localDeleteTargets = listOf(entry) }
                            )
                        }
                    }
                }
                item { Spacer(Modifier.height(4.dp)) }
            }
        }

        ToastHost(state.toast) { viewModel.consumeToast() }
    }

    state.preview?.let { preview ->
        PreviewOverlay(
            preview = preview,
            onClose = viewModel::closePreview,
            onOpenExternal = { viewModel.openPreviewExternally(preview) }
        )
    }

    createFolderFor?.let { page ->
        NameDialog(
            title = if (page == WorkspacePage.NAS) "新建 NAS 文件夹" else "新建手机文件夹",
            label = "文件夹名称",
            initial = "",
            confirmText = "创建",
            onDismiss = { createFolderFor = null },
            onConfirm = { name ->
                createFolderFor = null
                if (page == WorkspacePage.NAS) viewModel.createFolder(name) else viewModel.createLocalFolder(name)
            }
        )
    }
    if (remoteDeleteTargets.isNotEmpty()) {
        ConfirmDeleteDialog(
            count = remoteDeleteTargets.size,
            label = remoteDeleteTargets.singleOrNull()?.name,
            containsFolder = remoteDeleteTargets.any { it.directory },
            location = "NAS",
            onDismiss = { remoteDeleteTargets = emptyList() },
            onConfirm = {
                val targets = remoteDeleteTargets
                remoteDeleteTargets = emptyList()
                viewModel.deleteRemote(targets)
            }
        )
    }
    if (localDeleteTargets.isNotEmpty()) {
        ConfirmDeleteDialog(
            count = localDeleteTargets.size,
            label = localDeleteTargets.singleOrNull()?.name,
            containsFolder = localDeleteTargets.any { it.directory },
            location = "手机",
            onDismiss = { localDeleteTargets = emptyList() },
            onConfirm = {
                val targets = localDeleteTargets
                localDeleteTargets = emptyList()
                viewModel.deleteLocal(targets)
            }
        )
    }
    renameRemoteTarget?.let { entry ->
        NameDialog(
            title = "重命名（NAS）",
            label = "新名称",
            initial = entry.name,
            confirmText = "重命名",
            onDismiss = { renameRemoteTarget = null },
            onConfirm = { name ->
                renameRemoteTarget = null
                if (name != entry.name) viewModel.renameRemote(entry, name)
            }
        )
    }
    renameLocalTarget?.let { entry ->
        NameDialog(
            title = "重命名（手机）",
            label = "新名称",
            initial = entry.name,
            confirmText = "重命名",
            onDismiss = { renameLocalTarget = null },
            onConfirm = { name ->
                renameLocalTarget = null
                if (name != entry.name) viewModel.renameLocal(entry, name)
            }
        )
    }
    duplicateTarget?.let { entry ->
        NameDialog(
            title = "创建副本",
            label = "副本名称",
            initial = suggestCopyName(entry.name),
            confirmText = "创建副本",
            onDismiss = { duplicateTarget = null },
            onConfirm = { name ->
                duplicateTarget = null
                viewModel.duplicateLocal(entry, name)
            }
        )
    }
    if (editProfile) {
        ProfileDialog(
            endpoint = state.endpoint,
            canDelete = state.settings.endpoints.size > 1,
            onDismiss = { editProfile = false },
            onSave = { endpoint ->
                viewModel.updateConfig(endpoint)
                viewModel.connect()
                editProfile = false
            },
            onDelete = {
                viewModel.deleteActiveProfile()
                editProfile = false
            }
        )
    }
    if (settingsOpen) {
        SettingsDialog(
            state = state,
            onDismiss = { settingsOpen = false },
            onPickDownloadDir = { settingsOpen = false; downloadTreeLauncher.launch(null) },
            onResetDownloadDir = viewModel::clearDownloadTree
        )
    }
}

// ---- top chrome ----------------------------------------------------------------

@Composable
private fun HeroHeader(state: WorkspaceUiState, onSettings: () -> Unit) {
    Row(Modifier.fillMaxWidth(), verticalAlignment = Alignment.CenterVertically) {
        NexusLogo(Modifier.size(58.dp))
        Column(Modifier.padding(start = 12.dp).weight(1f)) {
            Text("WORKSPACE OS 2.0", color = Cyan, fontSize = 10.sp, fontWeight = FontWeight.Bold, letterSpacing = 1.4.sp)
            Text("NEXUS MOBILE", color = Ink, fontSize = 24.sp, fontWeight = FontWeight.Black)
            Text("本地优先 · NAS 协同 · 安全传输 · v0.5.4", color = Muted, fontSize = 12.sp)
        }
        Surface(
            modifier = Modifier.clickable(onClick = onSettings),
            color = if (state.connected) Color(0x2635D6A0) else Color(0x25FF6B8B),
            shape = RoundedCornerShape(18.dp),
            border = androidx.compose.foundation.BorderStroke(1.dp, if (state.connected) Green.copy(alpha = .45f) else Danger.copy(alpha = .4f))
        ) {
            Text(if (state.connected) "● 在线" else "● 配置", color = if (state.connected) Green else Warning, modifier = Modifier.padding(horizontal = 12.dp, vertical = 8.dp), fontSize = 12.sp, fontWeight = FontWeight.Bold)
        }
        Surface(
            modifier = Modifier.padding(start = 8.dp).clickable(onClick = onSettings),
            color = Panel,
            shape = RoundedCornerShape(18.dp),
            border = androidx.compose.foundation.BorderStroke(1.dp, Line)
        ) { Text("⚙", color = Cyan, fontSize = 14.sp, modifier = Modifier.padding(horizontal = 11.dp, vertical = 8.dp)) }
    }
}

@Composable
private fun ProfileBar(state: WorkspaceUiState, onSwitch: (String) -> Unit, onAdd: () -> Unit, onEdit: () -> Unit) {
    Row(
        Modifier.fillMaxWidth().horizontalScroll(rememberScrollState()),
        horizontalArrangement = Arrangement.spacedBy(8.dp),
        verticalAlignment = Alignment.CenterVertically
    ) {
        state.settings.endpoints.forEach { endpoint ->
            val active = endpoint.id == state.settings.activeId
            Surface(
                modifier = Modifier.clickable { if (!active) onSwitch(endpoint.id) else onEdit() },
                color = if (active) Color(0x337C5CFF) else Color(0x99101A35),
                shape = RoundedCornerShape(14.dp),
                border = androidx.compose.foundation.BorderStroke(1.dp, if (active) Accent.copy(alpha = .7f) else Line)
            ) {
                Row(Modifier.padding(horizontal = 12.dp, vertical = 8.dp), verticalAlignment = Alignment.CenterVertically) {
                    Text(endpoint.label, color = if (active) Ink else Muted, fontSize = 12.sp, fontWeight = FontWeight.Bold, maxLines = 1)
                    if (active) Text("✎", color = Cyan, fontSize = 11.sp, modifier = Modifier.padding(start = 6.dp))
                }
            }
        }
        Surface(
            modifier = Modifier.clickable(onClick = onAdd),
            color = Color(0x99101A35),
            shape = RoundedCornerShape(14.dp),
            border = androidx.compose.foundation.BorderStroke(1.dp, Green.copy(alpha = .45f))
        ) { Text("＋ 新 NAS", color = Green, fontSize = 12.sp, fontWeight = FontWeight.Bold, modifier = Modifier.padding(horizontal = 12.dp, vertical = 8.dp)) }
    }
}

@Composable
private fun NexusLogo(modifier: Modifier = Modifier) {
    Canvas(modifier) {
        val sx = size.width / 72f
        val sy = size.height / 72f
        val hex = Path().apply {
            moveTo(36f * sx, 4f * sy); lineTo(64f * sx, 20f * sy); lineTo(64f * sx, 52f * sy)
            lineTo(36f * sx, 68f * sy); lineTo(8f * sx, 52f * sy); lineTo(8f * sx, 20f * sy); close()
        }
        drawPath(hex, Accent.copy(alpha = .12f))
        drawPath(hex, Brush.linearGradient(listOf(Color(0xFF9B7CFF), Cyan)), style = Stroke(width = 2.4f * sx, join = StrokeJoin.Round))
        val letter = Path().apply {
            moveTo(22f * sx, 49f * sy); lineTo(22f * sx, 23f * sy); lineTo(50f * sx, 49f * sy); lineTo(50f * sx, 23f * sy)
        }
        drawPath(letter, Brush.linearGradient(listOf(Color(0xFF9B7CFF), Cyan)), style = Stroke(width = 5f * sx, cap = StrokeCap.Round, join = StrokeJoin.Round))
    }
}

@OptIn(ExperimentalMaterial3Api::class)
@Composable
private fun AnimatedConnectionCard(state: WorkspaceUiState, onConfig: (NasEndpoint) -> Unit, onConnect: () -> Unit) {
    var passwordVisible by remember { mutableStateOf(false) }
    TechCard {
        Row(Modifier.fillMaxWidth(), verticalAlignment = Alignment.CenterVertically) {
            Column(Modifier.weight(1f)) {
                Text("NAS CONTROL PLANE", color = Accent.copy(alpha = .95f), fontSize = 11.sp, fontWeight = FontWeight.Bold, letterSpacing = 1.sp)
                Text("${state.endpoint.host}  /  ${state.endpoint.share}", color = Ink, fontWeight = FontWeight.SemiBold, maxLines = 1, overflow = TextOverflow.Ellipsis)
            }
            if (state.busy) CircularProgressIndicator(Modifier.size(20.dp), color = Cyan, strokeWidth = 2.dp)
        }
        if (state.configExpanded) {
            Spacer(Modifier.height(12.dp))
            TechInput(state.endpoint.name, { onConfig(state.endpoint.copy(name = it)) }, "连接名称")
            Spacer(Modifier.height(8.dp))
            TechInput(state.endpoint.host, { onConfig(state.endpoint.copy(host = it)) }, "NAS 地址")
            Spacer(Modifier.height(8.dp))
            TechInput(state.endpoint.share, { onConfig(state.endpoint.copy(share = it)) }, "共享文件夹")
            Spacer(Modifier.height(8.dp))
            Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                TechInput(state.endpoint.username, { onConfig(state.endpoint.copy(username = it)) }, "用户名", Modifier.weight(1f))
                Box(Modifier.weight(1f)) {
                    TechInput(
                        state.endpoint.password,
                        { onConfig(state.endpoint.copy(password = it)) },
                        "密码",
                        password = !passwordVisible
                    )
                    TextButton(
                        onClick = { passwordVisible = !passwordVisible },
                        modifier = Modifier.align(Alignment.CenterEnd).padding(end = 4.dp)
                    ) { Text(if (passwordVisible) "隐藏" else "显示", color = Muted, fontSize = 11.sp) }
                }
            }
            Spacer(Modifier.height(10.dp))
            Button(
                onClick = onConnect,
                enabled = !state.busy && state.endpoint.ready,
                shape = RoundedCornerShape(14.dp),
                colors = ButtonDefaults.buttonColors(containerColor = Accent),
                modifier = Modifier.fillMaxWidth().height(48.dp)
            ) { Text(if (state.connected) "保存并重新连接" else "连接 Workspace NAS", fontWeight = FontWeight.Bold) }
        }
        Spacer(Modifier.height(8.dp))
        Text(state.status, color = if (state.status.startsWith("操作失败") || state.status.contains("失败")) Danger else Muted, fontSize = 12.sp, maxLines = 2, overflow = TextOverflow.Ellipsis)
    }
}

@OptIn(ExperimentalMaterial3Api::class)
@Composable
private fun TechInput(value: String, onValueChange: (String) -> Unit, label: String, modifier: Modifier = Modifier, password: Boolean = false) {
    OutlinedTextField(
        value = value,
        onValueChange = onValueChange,
        label = { Text(label) },
        singleLine = true,
        visualTransformation = if (password) PasswordVisualTransformation() else VisualTransformation.None,
        modifier = modifier.fillMaxWidth(),
        shape = RoundedCornerShape(14.dp),
        colors = OutlinedTextFieldDefaults.colors(
            focusedTextColor = Ink, unfocusedTextColor = Ink, focusedBorderColor = Accent, unfocusedBorderColor = Line,
            focusedLabelColor = Cyan, unfocusedLabelColor = Muted, cursorColor = Cyan,
            focusedContainerColor = Color(0x660B1228), unfocusedContainerColor = Color(0x440B1228)
        )
    )
}

@Composable
private fun StorageOverview(nas: StorageInfo, phone: StorageInfo, connected: Boolean) {
    Row(horizontalArrangement = Arrangement.spacedBy(10.dp), modifier = Modifier.fillMaxWidth()) {
        StorageCard("NAS 空间", if (connected) nas else StorageInfo(), Cyan, Modifier.weight(1f))
        StorageCard("手机空间", phone, Accent, Modifier.weight(1f))
    }
}

@Composable
private fun StorageCard(title: String, storage: StorageInfo, color: Color, modifier: Modifier) {
    Surface(modifier, color = Panel, shape = CardShape, border = androidx.compose.foundation.BorderStroke(1.dp, Line)) {
        Column(Modifier.padding(14.dp)) {
            Text(title, color = Muted, fontSize = 12.sp)
            Text(if (storage.totalBytes > 0) formatBytes(storage.freeBytes) else "--", color = Ink, fontSize = 20.sp, fontWeight = FontWeight.Bold)
            Text(if (storage.totalBytes > 0) "可用 / ${formatBytes(storage.totalBytes)}" else "等待连接", color = Muted, fontSize = 11.sp)
            Spacer(Modifier.height(9.dp))
            LinearProgressIndicator(progress = { storage.usedFraction }, modifier = Modifier.fillMaxWidth().height(6.dp).clip(CircleShape), color = color, trackColor = Color(0xFF202B49))
        }
    }
}

@Composable
private fun PageSwitcher(page: WorkspacePage, onChange: (WorkspacePage) -> Unit) {
    Surface(color = Color(0x99101A35), shape = RoundedCornerShape(18.dp), border = androidx.compose.foundation.BorderStroke(1.dp, Line)) {
        Row(Modifier.fillMaxWidth().padding(5.dp), horizontalArrangement = Arrangement.spacedBy(5.dp)) {
            PagePill("NAS 文件", page == WorkspacePage.NAS, Modifier.weight(1f)) { onChange(WorkspacePage.NAS) }
            PagePill("手机文件", page == WorkspacePage.PHONE, Modifier.weight(1f)) { onChange(WorkspacePage.PHONE) }
        }
    }
}

@Composable
private fun PagePill(label: String, selected: Boolean, modifier: Modifier, onClick: () -> Unit) {
    Box(
        modifier.clip(RoundedCornerShape(14.dp)).background(if (selected) Brush.horizontalGradient(listOf(Accent, Color(0xFF4F8DFF))) else Brush.horizontalGradient(listOf(Color.Transparent, Color.Transparent))).clickable(onClick = onClick).padding(vertical = 11.dp),
        contentAlignment = Alignment.Center
    ) { Text(label, color = if (selected) Color.White else Muted, fontWeight = FontWeight.Bold, fontSize = 13.sp) }
}

// ---- toolbars -------------------------------------------------------------------

@OptIn(ExperimentalMaterial3Api::class)
@Composable
private fun NasToolbar(
    state: WorkspaceUiState,
    onSearch: (String) -> Unit,
    onUp: () -> Unit,
    onRoot: () -> Unit,
    onRefresh: () -> Unit,
    onUpload: () -> Unit,
    onCreateFolder: () -> Unit,
    onSync: () -> Unit,
    onSelectAll: () -> Unit,
    onDelete: () -> Unit,
    onSort: (SortKey) -> Unit
) {
    TechCard {
        ToolbarTitle("NAS 文件", if (state.currentPath.isBlank()) "/ Workspace" else "/ ${state.currentPath}", state.selected.size)
        SearchField(state.search, onSearch, "搜索当前 NAS 目录")
        SortStrip(state.sortKey, state.sortAsc, onSort)
        GridActions(
            listOf(
                GridActionSpec("↑ 上一级", onUp, enabled = state.currentPath.isNotBlank() && !state.busy),
                GridActionSpec("⌂ 回根目录", onRoot, accent = Cyan, enabled = state.currentPath.isNotBlank() && !state.busy),
                GridActionSpec("⟳ 刷新", onRefresh, enabled = state.connected && !state.busy),
                GridActionSpec("☑ 全选", onSelectAll, enabled = state.entries.isNotEmpty() && !state.busy),
                GridActionSpec("▲ 上传文件", onUpload, primary = true, enabled = state.connected && !state.busy),
                GridActionSpec("＋ 新建文件夹", onCreateFolder, enabled = state.connected && !state.busy),
                GridActionSpec("↓ 同步到手机", onSync, accent = Green, enabled = state.selected.isNotEmpty() && !state.busy),
                GridActionSpec("✕ 删除", onDelete, accent = Danger, enabled = state.selected.isNotEmpty() && !state.busy)
            )
        )
        Text("提示：点文件行尾 ⋯ 可预览/重命名；左滑可删除", color = Muted, fontSize = 10.sp, modifier = Modifier.padding(top = 8.dp))
    }
}

@OptIn(ExperimentalMaterial3Api::class)
@Composable
private fun PhoneToolbar(
    state: WorkspaceUiState,
    onChooseRoot: () -> Unit,
    onSearch: (String) -> Unit,
    onUp: () -> Unit,
    onRoot: () -> Unit,
    onRefresh: () -> Unit,
    onSelectAll: () -> Unit,
    onCreateFolder: () -> Unit,
    onCopy: () -> Unit,
    onDelete: () -> Unit,
    onUpload: () -> Unit,
    onSort: (SortKey) -> Unit
) {
    val path = if (state.localRootUri == null) "尚未授权目录" else "/ ${listOf(state.localRootName, state.localPath.joinToString("/")).filter(String::isNotBlank).joinToString("/")}"
    TechCard {
        ToolbarTitle("手机文件", path, state.localSelected.size)
        SearchField(state.localSearch, onSearch, "搜索当前手机目录")
        SortStrip(state.sortKey, state.sortAsc, onSort)
        GridActions(
            listOf(
                GridActionSpec("⊞ 选择手机目录", onChooseRoot, primary = true, enabled = !state.busy),
                GridActionSpec("↑ 上一级", onUp, enabled = state.localPath.isNotEmpty() && !state.busy),
                GridActionSpec("⌂ 回根目录", onRoot, accent = Cyan, enabled = state.localPath.isNotEmpty() && !state.busy),
                GridActionSpec("⟳ 刷新", onRefresh, enabled = state.localRootUri != null && !state.busy),
                GridActionSpec("☑ 全选", onSelectAll, enabled = state.localEntries.isNotEmpty() && !state.busy),
                GridActionSpec("＋ 新建文件夹", onCreateFolder, enabled = state.localRootUri != null && !state.busy),
                GridActionSpec("⧉ 复制到…", onCopy, accent = Cyan, enabled = state.localSelected.isNotEmpty() && !state.busy),
                GridActionSpec("▲ 上传 NAS", onUpload, accent = Green, enabled = state.localSelected.isNotEmpty() && state.connected && !state.busy),
                GridActionSpec("✕ 删除", onDelete, accent = Danger, enabled = state.localSelected.isNotEmpty() && !state.busy)
            )
        )
        Text("可勾选文件或整个文件夹；复制和上传会保留子目录结构", color = Muted, fontSize = 10.sp, modifier = Modifier.padding(top = 8.dp))
    }
}

@Composable
private fun SortStrip(current: SortKey, asc: Boolean, onSort: (SortKey) -> Unit) {
    Spacer(Modifier.height(8.dp))
    Row(horizontalArrangement = Arrangement.spacedBy(6.dp), verticalAlignment = Alignment.CenterVertically) {
        Text("排序", color = Muted, fontSize = 11.sp)
        SortKey.values().forEach { key ->
            val selected = key == current
            Surface(
                modifier = Modifier.clickable { onSort(key) },
                color = if (selected) Color(0x337C5CFF) else Color(0x66101A35),
                shape = RoundedCornerShape(10.dp),
                border = androidx.compose.foundation.BorderStroke(1.dp, if (selected) Accent.copy(alpha = .6f) else Line)
            ) {
                Text(
                    if (selected) "${key.label} ${if (asc) "↑" else "↓"}" else key.label,
                    color = if (selected) Ink else Muted,
                    fontSize = 11.sp,
                    fontWeight = if (selected) FontWeight.Bold else FontWeight.Normal,
                    modifier = Modifier.padding(horizontal = 10.dp, vertical = 5.dp)
                )
            }
        }
    }
    Spacer(Modifier.height(6.dp))
}

@Composable
private fun ToolbarTitle(title: String, path: String, selectedCount: Int) {
    Row(Modifier.fillMaxWidth(), verticalAlignment = Alignment.CenterVertically) {
        Column(Modifier.weight(1f)) {
            Text(title, color = Ink, fontSize = 19.sp, fontWeight = FontWeight.Bold)
            Text(path, color = Cyan, fontSize = 12.sp, maxLines = 1, overflow = TextOverflow.Ellipsis)
        }
        Text("$selectedCount 已选", color = if (selectedCount == 0) Muted else Green, fontSize = 12.sp, fontWeight = FontWeight.Bold)
    }
}

@OptIn(ExperimentalMaterial3Api::class)
@Composable
private fun SearchField(value: String, onValueChange: (String) -> Unit, placeholder: String) {
    Spacer(Modifier.height(10.dp))
    OutlinedTextField(
        value = value,
        onValueChange = onValueChange,
        placeholder = { Text(placeholder, color = Muted) },
        leadingIcon = { Text("⌕", color = Cyan, fontSize = 22.sp) },
        trailingIcon = {
            if (value.isNotEmpty()) {
                TextButton(onClick = { onValueChange("") }) { Text("✕", color = Muted, fontSize = 14.sp) }
            }
        },
        singleLine = true,
        modifier = Modifier.fillMaxWidth().height(54.dp),
        shape = RoundedCornerShape(16.dp),
        colors = OutlinedTextFieldDefaults.colors(focusedTextColor = Ink, unfocusedTextColor = Ink, focusedBorderColor = Accent, unfocusedBorderColor = Line, cursorColor = Cyan, focusedContainerColor = PanelSoft, unfocusedContainerColor = PanelSoft)
    )
    Spacer(Modifier.height(10.dp))
}

private data class GridActionSpec(
    val label: String,
    val onClick: () -> Unit,
    val primary: Boolean = false,
    val accent: Color = Accent,
    val enabled: Boolean = true
)

/** Action buttons laid out as a fixed 3-column grid so rows always align. */
@Composable
private fun GridActions(specs: List<GridActionSpec>) {
    specs.chunked(3).forEachIndexed { index, row ->
        Row(
            Modifier.fillMaxWidth().padding(top = if (index == 0) 4.dp else 8.dp),
            horizontalArrangement = Arrangement.spacedBy(8.dp)
        ) {
            row.forEach { spec ->
                Box(Modifier.weight(1f)) { GridButton(spec) }
            }
            repeat(3 - row.size) { Spacer(Modifier.weight(1f)) }
        }
    }
}

@OptIn(ExperimentalMaterial3Api::class)
@Composable
private fun GridButton(spec: GridActionSpec) {
    Button(
        onClick = spec.onClick,
        enabled = spec.enabled,
        shape = RoundedCornerShape(14.dp),
        colors = ButtonDefaults.buttonColors(containerColor = if (spec.primary) spec.accent else Color(0xFF1A2546), contentColor = if (spec.primary) Color.White else spec.accent, disabledContainerColor = Color(0x661A2546), disabledContentColor = Muted.copy(alpha = .55f)),
        border = if (spec.primary) null else androidx.compose.foundation.BorderStroke(1.dp, spec.accent.copy(alpha = .32f)),
        contentPadding = PaddingValues(horizontal = 4.dp, vertical = 10.dp),
        modifier = Modifier.fillMaxWidth()
    ) { Text(spec.label, fontSize = 12.sp, fontWeight = FontWeight.SemiBold, maxLines = 1, overflow = TextOverflow.Ellipsis) }
}

// ---- file rows --------------------------------------------------------------------

@Composable
private fun RecentSyncedPanel(files: List<SyncedFile>, onOpen: (SyncedFile) -> Unit, onClear: () -> Unit) {
    TechCard {
        Row(verticalAlignment = Alignment.CenterVertically) {
            Text("✓ 最近同步到手机", color = Green, fontSize = 14.sp, fontWeight = FontWeight.Bold, modifier = Modifier.weight(1f))
            TextButton(onClick = onClear) { Text("清除", color = Muted, fontSize = 11.sp) }
        }
        Spacer(Modifier.height(4.dp))
        files.forEach { file ->
            Row(
                Modifier.fillMaxWidth().padding(vertical = 5.dp),
                verticalAlignment = Alignment.CenterVertically
            ) {
                Box(
                    Modifier.size(30.dp).clip(RoundedCornerShape(9.dp)).background(Green.copy(alpha = .14f)),
                    contentAlignment = Alignment.Center
                ) { Text(fileBadge(file.name), color = Green, fontWeight = FontWeight.Black, fontSize = 9.sp) }
                Column(Modifier.padding(start = 9.dp).weight(1f)) {
                    Text(file.name, color = Ink, fontSize = 13.sp, fontWeight = FontWeight.SemiBold, maxLines = 1, overflow = TextOverflow.Ellipsis)
                    Text(formatBytes(file.size), color = Muted, fontSize = 10.sp)
                }
                TextButton(onClick = { onOpen(file) }) { Text("打开", color = Green, fontWeight = FontWeight.Bold, fontSize = 12.sp) }
            }
        }
    }
}

@OptIn(ExperimentalMaterial3Api::class)
@Composable
private fun RemoteEntryRow(
    entry: RemoteEntry,
    selected: Boolean,
    onToggle: () -> Unit,
    onOpen: () -> Unit,
    onPreview: () -> Unit,
    onDownload: () -> Unit,
    onRename: () -> Unit,
    onDeleteRequested: () -> Unit
) {
    var menuOpen by remember { mutableStateOf(false) }
    SwipeDeleteContainer(onDeleteRequested) {
        FileRowSurface(
            name = entry.name,
            directory = entry.directory,
            size = entry.size,
            modifiedMillis = entry.modifiedMillis,
            selected = selected,
            onToggle = onToggle,
            onOpen = onOpen,
            trailingLabel = if (entry.directory) "打开" else "下载",
            trailingColor = if (entry.directory) Cyan else Green,
            onTrailing = if (entry.directory) onOpen else onDownload,
            menu = {
                DropdownMenu(expanded = menuOpen, onDismissRequest = { menuOpen = false }, containerColor = Color(0xFF141E3C)) {
                    if (!entry.directory) {
                        RowMenuItem("打开预览", Cyan) { menuOpen = false; onPreview() }
                        RowMenuItem("同步到手机", Green) { menuOpen = false; onDownload() }
                    }
                    RowMenuItem("重命名", Warning) { menuOpen = false; onRename() }
                    RowMenuItem("删除", Danger) { menuOpen = false; onDeleteRequested() }
                }
            },
            onMenu = { menuOpen = true }
        )
    }
}

@OptIn(ExperimentalMaterial3Api::class)
@Composable
private fun LocalEntryRow(
    entry: LocalEntry,
    selected: Boolean,
    onToggle: () -> Unit,
    onOpen: () -> Unit,
    onRename: () -> Unit,
    onDuplicate: () -> Unit,
    onDeleteRequested: () -> Unit
) {
    var menuOpen by remember { mutableStateOf(false) }
    SwipeDeleteContainer(onDeleteRequested) {
        FileRowSurface(
            name = entry.name,
            directory = entry.directory,
            size = entry.size,
            modifiedMillis = entry.modifiedMillis,
            selected = selected,
            onToggle = onToggle,
            onOpen = onOpen,
            trailingLabel = if (entry.directory) "打开" else "查看",
            trailingColor = if (entry.directory) Cyan else Accent,
            onTrailing = onOpen,
            menu = {
                DropdownMenu(expanded = menuOpen, onDismissRequest = { menuOpen = false }, containerColor = Color(0xFF141E3C)) {
                    if (!entry.directory) RowMenuItem("选择", Accent) { menuOpen = false; onToggle() }
                    RowMenuItem("创建副本", Cyan) { menuOpen = false; onDuplicate() }
                    RowMenuItem("重命名", Warning) { menuOpen = false; onRename() }
                    RowMenuItem("删除", Danger) { menuOpen = false; onDeleteRequested() }
                }
            },
            onMenu = { menuOpen = true }
        )
    }
}

@Composable
private fun RowMenuItem(text: String, color: Color, onClick: () -> Unit) {
    DropdownMenuItem(text = { Text(text, color = color, fontWeight = FontWeight.SemiBold, fontSize = 13.sp) }, onClick = onClick)
}

@OptIn(ExperimentalMaterial3Api::class)
@Composable
private fun SwipeDeleteContainer(onDeleteRequested: () -> Unit, content: @Composable RowScope.() -> Unit) {
    val scope = rememberCoroutineScope()
    val dismissState = rememberSwipeToDismissBoxState(
        positionalThreshold = { distance -> distance * .40f },
        confirmValueChange = { it != SwipeToDismissBoxValue.StartToEnd }
    )
    LaunchedEffect(dismissState.currentValue) {
        if (dismissState.currentValue == SwipeToDismissBoxValue.EndToStart) {
            delay(4_500)
            dismissState.reset()
        }
    }
    SwipeToDismissBox(
        state = dismissState,
        enableDismissFromStartToEnd = dismissState.currentValue == SwipeToDismissBoxValue.EndToStart,
        enableDismissFromEndToStart = true,
        modifier = Modifier.fillMaxWidth().clip(RoundedCornerShape(18.dp)),
        backgroundContent = {
            Box(
                Modifier.fillMaxSize().background(Brush.horizontalGradient(listOf(Color(0xFF161D37), Color(0xFF42172A)))).padding(horizontal = 12.dp),
                contentAlignment = Alignment.CenterEnd
            ) {
                Row(horizontalArrangement = Arrangement.spacedBy(8.dp), verticalAlignment = Alignment.CenterVertically) {
                    Surface(
                        color = Color(0xFF202A49),
                        shape = RoundedCornerShape(12.dp),
                        border = androidx.compose.foundation.BorderStroke(1.dp, Line),
                        modifier = Modifier.clickable { scope.launch { dismissState.reset() } }
                    ) { Text("取消", color = Ink, fontSize = 12.sp, fontWeight = FontWeight.Bold, modifier = Modifier.padding(horizontal = 14.dp, vertical = 10.dp)) }
                    Surface(
                        color = Danger,
                        shape = RoundedCornerShape(12.dp),
                        modifier = Modifier.clickable {
                            onDeleteRequested()
                            scope.launch { dismissState.reset() }
                        }
                    ) { Text("删除…", color = Color.White, fontSize = 12.sp, fontWeight = FontWeight.Black, modifier = Modifier.padding(horizontal = 14.dp, vertical = 10.dp)) }
                }
            }
        },
        content = content
    )
}

@Composable
private fun FileRowSurface(
    name: String,
    directory: Boolean,
    size: Long,
    modifiedMillis: Long,
    selected: Boolean,
    onToggle: () -> Unit,
    onOpen: () -> Unit,
    trailingLabel: String,
    trailingColor: Color,
    onTrailing: () -> Unit,
    menu: @Composable () -> Unit,
    onMenu: () -> Unit
) {
    Surface(
        modifier = Modifier.fillMaxWidth().clickable { if (directory) onOpen() else onToggle() },
        color = if (selected) Color(0xFF28244D) else Color(0xFF121A34),
        shape = RoundedCornerShape(18.dp),
        border = androidx.compose.foundation.BorderStroke(1.dp, if (selected) Accent.copy(alpha = .8f) else Line)
    ) {
        Row(Modifier.padding(horizontal = 10.dp, vertical = 10.dp), verticalAlignment = Alignment.CenterVertically) {
            Checkbox(checked = selected, onCheckedChange = { onToggle() }, colors = CheckboxDefaults.colors(checkedColor = Accent, uncheckedColor = Muted, checkmarkColor = Color.White))
            Box(
                Modifier.size(42.dp).clip(RoundedCornerShape(13.dp)).background(if (directory) Cyan.copy(alpha = .14f) else Accent.copy(alpha = .14f)),
                contentAlignment = Alignment.Center
            ) { Text(if (directory) "DIR" else fileBadge(name), color = if (directory) Cyan else Accent, fontWeight = FontWeight.Black, fontSize = 11.sp) }
            Column(Modifier.padding(start = 11.dp).weight(1f)) {
                Text(name, color = Ink, fontWeight = FontWeight.SemiBold, maxLines = 1, overflow = TextOverflow.Ellipsis)
                Text(if (directory) "文件夹 · ${formatTime(modifiedMillis)}" else "${formatBytes(size)} · ${formatTime(modifiedMillis)}", color = Muted, fontSize = 11.sp, maxLines = 1)
            }
            Box {
                TextButton(onClick = onMenu, shape = RoundedCornerShape(12.dp)) {
                    Text("⋯", color = Muted, fontSize = 18.sp, modifier = Modifier.padding(horizontal = 4.dp))
                }
                menu()
            }
            TextButton(onClick = onTrailing, shape = RoundedCornerShape(12.dp)) {
                Text(trailingLabel, color = trailingColor, fontWeight = FontWeight.Bold, fontSize = 12.sp)
            }
        }
    }
}

// ---- task center & toast --------------------------------------------------------------

@Composable
private fun TaskCenter(task: TransferState, onClear: () -> Unit, onCancel: () -> Unit) {
    Surface(
        modifier = Modifier.fillMaxWidth().navigationBarsPadding().padding(horizontal = 12.dp, vertical = 8.dp),
        color = Color(0xF2182140),
        shape = RoundedCornerShape(20.dp),
        shadowElevation = 12.dp,
        border = androidx.compose.foundation.BorderStroke(1.dp, if (task.failed) Danger.copy(alpha = .7f) else Accent.copy(alpha = .55f))
    ) {
        Column(Modifier.padding(14.dp)) {
            Row(verticalAlignment = Alignment.CenterVertically) {
                Column(Modifier.weight(1f)) {
                    Text("后台任务 · ${task.title}", color = Ink, fontWeight = FontWeight.Bold, fontSize = 13.sp)
                    Text(task.message.ifBlank { task.currentFile.ifBlank { "准备处理…" } }, color = if (task.failed) Danger else Muted, fontSize = 11.sp, maxLines = 1, overflow = TextOverflow.Ellipsis)
                }
                val percent = (task.fraction * 100).roundToInt()
                Text("$percent%", color = if (task.completed) Green else Cyan, fontWeight = FontWeight.Black)
                if (!task.completed && !task.failed) {
                    TextButton(onClick = onCancel) { Text("取消", color = Danger, fontSize = 11.sp) }
                }
                if (task.failed || task.completed) TextButton(onClick = onClear) { Text("清除", color = Muted, fontSize = 11.sp) }
            }
            Spacer(Modifier.height(7.dp))
            if (task.totalBytes > 0 || task.totalFiles > 0) {
                LinearProgressIndicator(progress = { task.fraction }, modifier = Modifier.fillMaxWidth().height(7.dp).clip(CircleShape), color = if (task.failed) Danger else if (task.completed) Green else Accent, trackColor = Color(0xFF293252))
            } else {
                LinearProgressIndicator(modifier = Modifier.fillMaxWidth().height(7.dp).clip(CircleShape), color = Accent, trackColor = Color(0xFF293252))
            }
            Text("${task.completedFiles}/${task.totalFiles} 项${if (task.totalBytes > 0) " · ${formatBytes(task.copiedBytes)} / ${formatBytes(task.totalBytes)}" else ""}", color = Muted, fontSize = 10.sp, modifier = Modifier.padding(top = 5.dp))
        }
    }
}

@Composable
private fun ToastHost(message: String?, onDismiss: () -> Unit) {
    LaunchedEffect(message) {
        if (message != null) {
            delay(2_800)
            onDismiss()
        }
    }
    Box(Modifier.fillMaxSize(), contentAlignment = Alignment.BottomCenter) {
        AnimatedVisibility(
            visible = message != null,
            enter = fadeIn() + slideInVertically { it / 3 },
            exit = fadeOut(),
            modifier = Modifier.navigationBarsPadding().padding(bottom = 96.dp, start = 24.dp, end = 24.dp)
        ) {
        Surface(
            color = Color(0xF21C2A4E),
            shape = RoundedCornerShape(16.dp),
            border = androidx.compose.foundation.BorderStroke(1.dp, Cyan.copy(alpha = .5f)),
            modifier = Modifier.clickable(onClick = onDismiss)
        ) {
            Text(message.orEmpty(), color = Ink, fontSize = 13.sp, fontWeight = FontWeight.SemiBold, maxLines = 2, overflow = TextOverflow.Ellipsis, modifier = Modifier.padding(horizontal = 16.dp, vertical = 11.dp))
        }
        }
    }
}

// ---- in-app preview ------------------------------------------------------------------

@androidx.compose.runtime.Composable
private fun PreviewOverlay(preview: PreviewState, onClose: () -> Unit, onOpenExternal: () -> Unit) {
    androidx.compose.ui.window.Dialog(
        onDismissRequest = onClose,
        properties = androidx.compose.ui.window.DialogProperties(dismissOnBackPress = true, dismissOnClickOutside = false)
    ) {
        Box(
            Modifier
                .fillMaxSize()
                .background(Color(0xF2050816))
                .statusBarsPadding()
        ) {
            Row(
                Modifier.fillMaxWidth().padding(horizontal = 8.dp, vertical = 6.dp),
                verticalAlignment = Alignment.CenterVertically
            ) {
                TextButton(onClick = onClose) { Text("✕ 关闭", color = Ink, fontSize = 13.sp, fontWeight = FontWeight.Bold) }
                Text(
                    preview.name,
                    color = Ink,
                    fontSize = 14.sp,
                    fontWeight = FontWeight.SemiBold,
                    maxLines = 1,
                    overflow = TextOverflow.Ellipsis,
                    modifier = Modifier.weight(1f).padding(horizontal = 6.dp)
                )
                if (preview.kind == PreviewKind.IMAGE || preview.kind == PreviewKind.MARKDOWN) {
                    TextButton(onClick = onOpenExternal) { Text("其他应用", color = Cyan, fontSize = 12.sp) }
                }
            }
            Box(Modifier.fillMaxSize().padding(top = 52.dp, bottom = 12.dp)) {
                when (preview.kind) {
                    PreviewKind.IMAGE -> ZoomableImage(uri = preview.uri)
                    PreviewKind.MARKDOWN -> MarkdownView(source = preview.text.orEmpty())
                    PreviewKind.TEXT -> ReadOnlyTextView(text = preview.text.orEmpty())
                }
            }
        }
    }
}

@Composable
private fun ZoomableImage(uri: Uri) {
    val context = androidx.compose.ui.platform.LocalContext.current
    var bitmap by remember(uri) { mutableStateOf<android.graphics.Bitmap?>(null) }
    var failed by remember(uri) { mutableStateOf(false) }
    LaunchedEffect(uri) {
        kotlinx.coroutines.withContext(kotlinx.coroutines.Dispatchers.IO) {
            runCatching {
                // Bounds pass first: pick an inSampleSize so huge NAS photos do not OOM.
                val bounds = BitmapFactory.Options().apply { inJustDecodeBounds = true }
                context.contentResolver.openInputStream(uri)?.use { BitmapFactory.decodeStream(it, null, bounds) }
                if (bounds.outWidth <= 0) error("无法解码图片")
                var sample = 1
                while (bounds.outWidth / sample > 2048 || bounds.outHeight / sample > 2048) sample *= 2
                val options = BitmapFactory.Options().apply { inSampleSize = sample }
                context.contentResolver.openInputStream(uri)?.use { BitmapFactory.decodeStream(it, null, options) }
            }.onSuccess { decoded -> bitmap = decoded }
                .onFailure { failed = true }
        }
    }
    var scale by remember(uri) { mutableStateOf(1f) }
    var offset by remember(uri) { mutableStateOf(androidx.compose.ui.geometry.Offset.Zero) }
    when {
        failed -> CenterHint("图片格式不支持应用内预览，可点「其他应用」打开")
        bitmap == null -> Box(Modifier.fillMaxSize(), contentAlignment = Alignment.Center) {
            androidx.compose.material3.CircularProgressIndicator(Modifier.size(28.dp), color = Cyan)
        }
        else -> Image(
            bitmap = bitmap!!.asImageBitmap(),
            contentDescription = "图片预览",
            contentScale = ContentScale.Fit,
            modifier = Modifier
                .fillMaxSize()
                .padding(12.dp)
                .graphicsLayer(
                    scaleX = scale,
                    scaleY = scale,
                    translationX = offset.x,
                    translationY = offset.y
                )
                .pointerInput(uri) {
                    detectTransformGestures { _, pan, zoom, _ ->
                        scale = (scale * zoom).coerceIn(1f, 6f)
                        offset = if (scale <= 1.05f) androidx.compose.ui.geometry.Offset.Zero
                        else offset + pan * scale
                    }
                }
        )
    }
}

@Composable
private fun ReadOnlyTextView(text: String) {
    Box(
        Modifier
            .fillMaxSize()
            .padding(horizontal = 12.dp)
            .clip(RoundedCornerShape(16.dp))
            .background(Color(0xCC0B1228))
            .verticalScroll(rememberScrollState())
    ) {
        Text(
            text.ifBlank { "（空文件）" },
            color = Ink,
            fontSize = 13.sp,
            fontFamily = FontFamily.Monospace,
            modifier = Modifier.padding(14.dp)
        )
    }
}

@Composable
private fun MarkdownView(source: String) {
    val rendered = remember(source) { renderMarkdown(source) }
    Box(
        Modifier
            .fillMaxSize()
            .padding(horizontal = 12.dp)
            .clip(RoundedCornerShape(16.dp))
            .background(Color(0xCC0B1228))
            .verticalScroll(rememberScrollState())
    ) {
        Text(
            rendered,
            color = Ink,
            fontSize = 14.sp,
            lineHeight = 22.sp,
            modifier = Modifier.padding(16.dp)
        )
    }
}

@Composable
private fun CenterHint(text: String) {
    Box(Modifier.fillMaxSize(), contentAlignment = Alignment.Center) {
        Text(text, color = Muted, fontSize = 13.sp, modifier = Modifier.padding(24.dp))
    }
}

/** Lightweight, dependency-free Markdown renderer (headings, emphasis, lists, code, quotes). */
private fun renderMarkdown(source: String): AnnotatedString = buildAnnotatedString {
    var inCodeBlock = false
    source.replace("\r\n", "\n").lines().forEach { rawLine ->
        val line = rawLine.trimEnd()
        when {
            line.startsWith("```") -> {
                inCodeBlock = !inCodeBlock
                withStyle(SpanStyle(color = Cyan, fontFamily = FontFamily.Monospace, fontSize = 13.sp)) { append("\n") }
            }
            inCodeBlock -> withStyle(SpanStyle(color = Green, fontFamily = FontFamily.Monospace, fontSize = 13.sp)) {
                append(line)
                append("\n")
            }
            line.startsWith("#") -> {
                val level = line.takeWhile { it == '#' }.length.coerceAtMost(4)
                val body = line.drop(level).trim()
                withStyle(SpanStyle(color = Cyan, fontSize = (26 - level * 3).sp, fontWeight = FontWeight.Black)) {
                    append(body)
                }
                append("\n\n")
            }
            line.startsWith(">") -> withStyle(SpanStyle(color = Muted, fontStyle = FontStyle.Italic)) {
                append(line.dropWhile { it == '>' || it == ' ' })
                append("\n")
            }
            line.startsWith("- ") || line.startsWith("* ") -> {
                append("• ")
                appendInline(line.drop(2))
                append("\n")
            }
            Regex("^\\d+\\.\\s").containsMatchIn(line) -> {
                append(Regex("^\\d+\\.").find(line)!!.value)
                append(" ")
                appendInline(line.substringAfter(' ').trim())
                append("\n")
            }
            line.isBlank() -> append("\n")
            else -> {
                appendInline(line)
                append("\n")
            }
        }
    }
}

private fun androidx.compose.ui.text.AnnotatedString.Builder.appendInline(text: String) {
    val pattern = Regex("""(\*\*[^*]+\*\*|\*[^*]+\*|`[^`]+`|\[[^\]]+\]\([^)]+\))""")
    var cursor = 0
    pattern.findAll(text).forEach { match ->
        if (match.range.first > cursor) append(text.substring(cursor, match.range.first))
        val token = match.value
        when {
            token.startsWith("**") -> withStyle(SpanStyle(fontWeight = FontWeight.Bold)) { append(token.trim('*')) }
            token.startsWith("`") -> withStyle(SpanStyle(color = Warning, fontFamily = FontFamily.Monospace, fontSize = 13.sp)) { append(token.trim('`')) }
            token.startsWith("[") -> {
                val label = token.substringAfter('[').substringBefore(']')
                withStyle(SpanStyle(color = Cyan, textDecoration = TextDecoration.Underline)) { append(label) }
            }
            else -> withStyle(SpanStyle(fontStyle = FontStyle.Italic)) { append(token.trim('*')) }
        }
        cursor = match.range.last + 1
    }
    if (cursor < text.length) append(text.substring(cursor))
}

// ---- dialogs ---------------------------------------------------------------------------

@Composable
private fun NameDialog(title: String, label: String, initial: String, confirmText: String, onDismiss: () -> Unit, onConfirm: (String) -> Unit) {
    var name by remember { mutableStateOf(initial) }
    AlertDialog(
        onDismissRequest = onDismiss,
        containerColor = Color(0xFF121B35),
        shape = CardShape,
        title = { Text(title, color = Ink, fontWeight = FontWeight.Bold) },
        text = { TechInput(name, { name = it }, label) },
        confirmButton = { Button(onClick = { onConfirm(name) }, enabled = name.trim().isNotBlank(), colors = ButtonDefaults.buttonColors(containerColor = Accent), shape = RoundedCornerShape(12.dp)) { Text(confirmText) } },
        dismissButton = { TextButton(onClick = onDismiss) { Text("取消", color = Muted) } }
    )
}

@OptIn(ExperimentalMaterial3Api::class)
@Composable
private fun ProfileDialog(endpoint: NasEndpoint, canDelete: Boolean, onDismiss: () -> Unit, onSave: (NasEndpoint) -> Unit, onDelete: () -> Unit) {
    var draft by remember { mutableStateOf(endpoint) }
    var passwordVisible by remember { mutableStateOf(false) }
    AlertDialog(
        onDismissRequest = onDismiss,
        containerColor = Color(0xFF121B35),
        shape = CardShape,
        title = { Text("连接设置 · ${endpoint.label}", color = Ink, fontWeight = FontWeight.Bold) },
        text = {
            Column(verticalArrangement = Arrangement.spacedBy(8.dp)) {
                TechInput(draft.name, { draft = draft.copy(name = it) }, "连接名称")
                TechInput(draft.host, { draft = draft.copy(host = it) }, "NAS 地址")
                TechInput(draft.share, { draft = draft.copy(share = it) }, "共享文件夹")
                TechInput(draft.username, { draft = draft.copy(username = it) }, "用户名")
                Box {
                    TechInput(draft.password, { draft = draft.copy(password = it) }, "密码", password = !passwordVisible)
                    TextButton(onClick = { passwordVisible = !passwordVisible }, modifier = Modifier.align(Alignment.CenterEnd)) {
                        Text(if (passwordVisible) "隐藏" else "显示", color = Muted, fontSize = 11.sp)
                    }
                }
                Text("密码仅在本机用 Android Keystore 加密保存。", color = Muted, fontSize = 11.sp)
            }
        },
        confirmButton = { Button(onClick = { onSave(draft) }, colors = ButtonDefaults.buttonColors(containerColor = Accent), shape = RoundedCornerShape(12.dp)) { Text("保存并连接") } },
        dismissButton = {
            Row {
                if (canDelete) TextButton(onClick = onDelete) { Text("删除", color = Danger, fontSize = 13.sp) }
                TextButton(onClick = onDismiss) { Text("取消", color = Muted) }
            }
        }
    )
}

@Composable
private fun SettingsDialog(
    state: WorkspaceUiState,
    onDismiss: () -> Unit,
    onPickDownloadDir: () -> Unit,
    onResetDownloadDir: () -> Unit
) {
    AlertDialog(
        onDismissRequest = onDismiss,
        containerColor = Color(0xFF121B35),
        shape = CardShape,
        title = { Text("设置", color = Ink, fontWeight = FontWeight.Bold) },
        text = {
            Column(verticalArrangement = Arrangement.spacedBy(10.dp)) {
                Text("NAS 下载目录", color = Muted, fontSize = 12.sp)
                Surface(
                    color = Color(0x660B1228),
                    shape = RoundedCornerShape(14.dp),
                    border = androidx.compose.foundation.BorderStroke(1.dp, Line),
                    modifier = Modifier.fillMaxWidth()
                ) {
                    Column(Modifier.padding(12.dp)) {
                        Text(
                            state.downloadDirLabel,
                            color = Ink,
                            fontSize = 14.sp,
                            fontWeight = FontWeight.SemiBold,
                            maxLines = 2,
                            overflow = TextOverflow.Ellipsis
                        )
                        Text(state.downloadDirHint, color = Muted, fontSize = 11.sp, modifier = Modifier.padding(top = 3.dp))
                    }
                }
                Row(horizontalArrangement = Arrangement.spacedBy(8.dp), modifier = Modifier.fillMaxWidth()) {
                    Button(
                        onClick = onPickDownloadDir,
                        shape = RoundedCornerShape(12.dp),
                        colors = ButtonDefaults.buttonColors(containerColor = Accent),
                        modifier = Modifier.weight(1f)
                    ) { Text(if (state.downloadTreeUri == null) "选择文件夹…" else "更换文件夹…", fontWeight = FontWeight.Bold, fontSize = 13.sp) }
                    if (state.downloadTreeUri != null) {
                        OutlinedButton(
                            onClick = onResetDownloadDir,
                            shape = RoundedCornerShape(12.dp),
                            border = androidx.compose.foundation.BorderStroke(1.dp, Line),
                            colors = ButtonDefaults.outlinedButtonColors(contentColor = Muted),
                            modifier = Modifier.weight(1f)
                        ) { Text("恢复默认", fontSize = 13.sp) }
                    }
                }
                Text("点击「选择文件夹」弹出系统目录选择器，授权后 NAS 文件将直接保存到所选位置；默认保存到 Download/WorkspaceOS。", color = Muted, fontSize = 11.sp)
                Text("版本 v0.5.4 · Workspace OS NEXUS MOBILE", color = Muted, fontSize = 11.sp)
            }
        },
        confirmButton = { TextButton(onClick = onDismiss) { Text("完成", color = Cyan, fontWeight = FontWeight.Bold) } }
    )
}

@Composable
private fun ConfirmDeleteDialog(count: Int, label: String?, containsFolder: Boolean, location: String, onDismiss: () -> Unit, onConfirm: () -> Unit) {
    AlertDialog(
        onDismissRequest = onDismiss,
        containerColor = Color(0xFF17192D),
        shape = CardShape,
        title = { Text("确认删除", color = Ink, fontWeight = FontWeight.Black) },
        text = {
            Column(verticalArrangement = Arrangement.spacedBy(8.dp)) {
                Text(if (label != null) "将从${location}删除“$label”" else "将从${location}删除已选的 $count 个项目", color = Ink)
                if (containsFolder) Text("包含文件夹时会递归删除其中全部内容，此操作无法撤销。", color = Danger, fontSize = 12.sp, fontWeight = FontWeight.Bold)
                else Text("此操作无法撤销。", color = Muted, fontSize = 12.sp)
            }
        },
        confirmButton = { Button(onClick = onConfirm, colors = ButtonDefaults.buttonColors(containerColor = Danger), shape = RoundedCornerShape(12.dp)) { Text("确认删除", fontWeight = FontWeight.Bold) } },
        dismissButton = { TextButton(onClick = onDismiss) { Text("取消", color = Muted) } }
    )
}

@Composable
private fun EmptyPanel(text: String) {
    TechCard {
        Box(Modifier.fillMaxWidth().height(130.dp), contentAlignment = Alignment.Center) {
            Column(horizontalAlignment = Alignment.CenterHorizontally) {
                Text("◇", color = Accent, fontSize = 32.sp)
                Text(text, color = Muted, fontSize = 13.sp)
            }
        }
    }
}

@Composable
private fun TechCard(content: @Composable ColumnScope.() -> Unit) {
    Surface(color = Panel, shape = CardShape, border = androidx.compose.foundation.BorderStroke(1.dp, Line), modifier = Modifier.fillMaxWidth()) {
        Column(Modifier.padding(16.dp), content = content)
    }
}

// ---- helpers ------------------------------------------------------------------------------

private fun suggestCopyName(name: String): String {
    val dot = name.lastIndexOf('.')
    return if (dot > 0) "${name.substring(0, dot)} 副本${name.substring(dot)}" else "$name 副本"
}

private fun fileBadge(name: String): String = name.substringAfterLast('.', "FILE").uppercase().take(4)

private fun formatBytes(value: Long): String {
    if (value < 0) return "--"
    val units = arrayOf("B", "KB", "MB", "GB", "TB")
    var amount = value.toDouble()
    var unit = 0
    while (amount >= 1024 && unit < units.lastIndex) { amount /= 1024; unit++ }
    return if (unit == 0) "${amount.toLong()} ${units[unit]}" else String.format(Locale.US, "%.1f %s", amount, units[unit])
}

private fun formatTime(millis: Long): String = if (millis <= 0) "--" else SimpleDateFormat("MM-dd HH:mm", Locale.getDefault()).format(Date(millis))
