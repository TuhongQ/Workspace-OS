#!/usr/bin/env python3
"""macOS control center for Workspace OS 2.0 (standard-library only)."""
from __future__ import annotations

import datetime as dt
import json
import os
import re
import signal
import socket
import subprocess
import sys
import threading
import time
import urllib.request
from pathlib import Path
from typing import Callable
import tkinter as tk
from tkinter import filedialog, messagebox, ttk
from urllib.parse import unquote, urlparse


ROOT = (Path(getattr(sys, "_MEIPASS")) / "WorkspaceOS") if getattr(sys, "frozen", False) else Path(__file__).resolve().parents[2]
if os.environ.get("WORKSPACE_OS_ROOT"):
    ROOT = Path(os.environ["WORKSPACE_OS_ROOT"]).resolve()
CLI = ROOT / "scripts" / "python" / "workspace_cli.py"
SYNC_SERVER = ROOT / "scripts" / "python" / "dashboard_sync_server.py"
SETTINGS_PATH = Path.home() / "Library" / "Application Support" / "WorkspaceOS" / "control-center-settings.json"
HELP_FILE = ROOT / "docs" / "使用说明与功能介绍.md"
LOG_PATH = Path.home() / "Library" / "Logs" / "WorkspaceOS" / "dashboard.log"
DASHBOARD_RUNTIME_DIR = Path.home() / "Library" / "Caches" / "WorkspaceOS" / "dashboard"
FROZEN_HELPER = Path(sys.executable).with_name("WorkspaceOSHelper")

BG = "#080B13"
PANEL = "#101622"
PANEL_SOFT = "#161E2D"
PANEL_HOVER = "#1C2738"
PANEL_DARK = "#0B101B"
CARD = "#121A29"
CARD_HOVER = "#1A2639"
LINE = "#2A3548"
TEXT = "#F4F7FC"
MUTED = "#8995AA"
MUTED_STRONG = "#B6C0D1"
ACCENT = "#7864F6"
ACCENT_HOVER = "#8B78FF"
ACCENT_SOFT = "#242044"
CYAN = "#5AD5E5"
GOOD = "#50D7A2"
GOOD_SOFT = "#153329"
WARN = "#F3C46B"
WARN_SOFT = "#352B19"


def normalize_quickconnect_id(value: str) -> str:
    """Accept a QuickConnect ID or pasted QuickConnect URL, never credentials."""
    raw = str(value or "").strip()
    if "://" in raw:
        parsed = urlparse(raw)
        if parsed.query or parsed.fragment:
            raise ValueError("QuickConnect 输入不能包含密码或其他参数")
        raw = parsed.path.strip("/").split("/", 1)[0]
    elif raw.lower().startswith(("quickconnect.to/", "quickconnect.cn/")):
        raw = raw.split("/", 1)[1].split("/", 1)[0]
    else:
        raw = raw.split("/", 1)[0]
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{2,63}", raw):
        raise ValueError("QuickConnect ID 格式无效")
    return raw


class NexusButton(tk.Canvas):
    """Borderless rounded control with a visible keyboard-focus state."""

    def __init__(
        self, parent, title: str, command: Callable[[], None], *, subtitle: str = "",
        icon: str = "", primary: bool = False, compact: bool = True, width: int | None = None,
    ) -> None:
        self.primary = primary
        self.normal_bg = ACCENT if primary else PANEL_SOFT if compact else CARD
        self.hover_bg = ACCENT_HOVER if primary else PANEL_HOVER if compact else CARD_HOVER
        self.normal_fg = "#FFFFFF" if primary else TEXT
        self.title = title
        self.subtitle = subtitle
        self.icon = icon
        self.compact = compact
        self.command = command
        self.state = "normal"
        self.focused = False
        try:
            parent_bg = parent.cget("bg")
        except tk.TclError:
            parent_bg = BG
        super().__init__(
            parent, bg=parent_bg, highlightthickness=0, bd=0,
            height=40 if compact else 72, width=width or (104 if compact else 160),
            cursor="pointinghand", takefocus=1,
        )
        self.current_bg = self.normal_bg
        self.bind("<Configure>", self._draw)
        self.bind("<Button-1>", self._invoke)
        self.bind("<Return>", self._invoke)
        self.bind("<space>", self._invoke)
        self.bind("<Enter>", self._enter)
        self.bind("<Leave>", self._leave)
        self.bind("<FocusIn>", self._focus_in)
        self.bind("<FocusOut>", self._focus_out)

    def _rounded_rectangle(self, canvas_width: int, canvas_height: int, radius: int, **kwargs) -> None:
        points = [
            radius, 1, canvas_width - radius, 1, canvas_width - 1, 1, canvas_width - 1, radius,
            canvas_width - 1, canvas_height - radius, canvas_width - 1, canvas_height - 1,
            canvas_width - radius, canvas_height - 1, radius, canvas_height - 1, 1, canvas_height - 1,
            1, canvas_height - radius, 1, radius, 1, 1,
        ]
        self.create_polygon(points, smooth=True, splinesteps=24, **kwargs)

    def _draw(self, _event=None) -> None:
        self.delete("all")
        width = max(20, self.winfo_width())
        height = max(20, self.winfo_height())
        foreground = MUTED if self.state == "disabled" else self.normal_fg
        self._rounded_rectangle(
            width, height, 12 if self.compact else 15,
            fill=self.current_bg,
            outline=ACCENT_HOVER if self.focused else self.current_bg,
            width=2 if self.focused else 1,
        )
        if self.compact:
            self.create_text(
                width / 2, height / 2, text=self.title, fill=foreground,
                font=("Helvetica Neue", 10, "bold"), anchor="center",
            )
            return
        center_y = height / 2
        interactive = self.current_bg == self.hover_bg or self.focused
        if interactive:
            self.create_line(2, 21, 2, height - 21, fill=ACCENT_HOVER, width=2)
        self.create_line(width - 45, 11, width - 29, 11, fill="#2B3750", width=1)
        self.create_line(
            width - 25, 11, width - 15, 11,
            fill=CYAN if interactive else "#315865", width=2,
        )
        icon_fill = "#FFFFFF" if self.primary else ACCENT_SOFT
        icon_foreground = MUTED if self.state == "disabled" else "#FFFFFF" if self.primary else CYAN
        orbit = ACCENT_HOVER if interactive else "#383064"
        self.create_oval(11, center_y - 18, 47, center_y + 18, fill="#181B34", outline=orbit, width=1)
        self.create_oval(16, center_y - 13, 42, center_y + 13, fill=icon_fill, outline="")
        self.create_text(
            29, center_y, text=self.icon or "◇", fill=icon_foreground,
            font=("Helvetica Neue", 11, "bold"), anchor="center",
        )
        title_size = 9 if width < 180 else 10
        subtitle_size = 8 if width < 180 else 9
        self.create_text(
            57, center_y - 13, text=self.title, fill=foreground,
            font=("Helvetica Neue", title_size, "bold"), anchor="w", width=max(40, width - 80),
        )
        if self.subtitle:
            self.create_text(
                57, center_y + 14, text=self.subtitle, fill=MUTED,
                font=("Helvetica Neue", subtitle_size), anchor="w", width=max(40, width - 80),
            )
        self.create_text(
            width - 17, height / 2, text="›", fill=MUTED,
            font=("Helvetica Neue", 16), anchor="center",
        )

    def _enter(self, _event=None) -> None:
        if self.state == "normal":
            self.current_bg = self.hover_bg
            self._draw()

    def _leave(self, _event=None) -> None:
        self.current_bg = self.normal_bg
        self._draw()

    def _focus_in(self, _event=None) -> None:
        self.focused = True
        self._draw()

    def _focus_out(self, _event=None) -> None:
        self.focused = False
        self._draw()

    def _invoke(self, _event=None) -> None:
        if self.state == "normal":
            self.focus_set()
            self.command()

    def configure(self, cnf=None, **kwargs):
        state = kwargs.pop("state", None)
        if state is not None:
            self.state = str(state)
            super().configure(cursor="arrow" if self.state == "disabled" else "pointinghand")
            self._draw()
        if cnf is not None or kwargs:
            return super().configure(cnf, **kwargs)
        return None

    config = configure


class WorkspaceOSApp(tk.Tk):
    def __init__(self) -> None:
        super().__init__()
        settings = self.load_settings()
        saved_nas = str(settings.get("nas_path") or "/Volumes/Workspace").strip()
        self.migrated_nas_url = saved_nas if saved_nas.lower().startswith("smb://") else ""
        if self.migrated_nas_url:
            share_name = Path(unquote(urlparse(saved_nas).path)).name or "Workspace"
            saved_nas = str(Path("/Volumes") / share_name)
        self.title("Workspace OS 2.0")
        width = min(1200, max(980, self.winfo_screenwidth() - 80))
        height = min(800, max(700, self.winfo_screenheight() - 80))
        left = max(0, (self.winfo_screenwidth() - width) // 2)
        top = max(0, (self.winfo_screenheight() - height) // 2)
        self.geometry(f"{width}x{height}+{left}+{top}")
        self.minsize(980, 700)
        self.configure(bg=BG)
        self.workspace = tk.StringVar(value=str(settings.get("workspace_path") or Path.home() / "Workspace"))
        self.nas_path = tk.StringVar(value=saved_nas)
        self.quickconnect_id = tk.StringVar(value=str(settings.get("quickconnect_id") or "").strip())
        self.search_query = tk.StringVar()
        self.dashboard_process: subprocess.Popen[str] | None = None
        self.dashboard_log_handle = None
        self.child_processes: set[subprocess.Popen[str]] = set()
        self.child_process_lock = threading.Lock()
        self.busy_count = 0
        self.status_reset_job: str | None = None
        self.action_buttons: list[tk.Widget] = []
        self.protocol("WM_DELETE_WINDOW", self.close_app)
        self._build_style()
        self._build_ui()
        self.log("控制中心已准备就绪。")
        self.log(f"NAS：{self.nas_path.get()}")
        if self.migrated_nas_url:
            self.log("已把旧版 SMB 地址转换为 macOS 挂载路径；NAS 登录仍由 Finder 和钥匙串管理。")

    @staticmethod
    def load_settings() -> dict:
        try:
            value = json.loads(SETTINGS_PATH.read_text(encoding="utf-8-sig"))
            return value if isinstance(value, dict) else {}
        except (OSError, UnicodeDecodeError, json.JSONDecodeError):
            return {}

    def save_settings(self) -> None:
        try:
            SETTINGS_PATH.parent.mkdir(parents=True, exist_ok=True)
            saved = {}
            if SETTINGS_PATH.is_file():
                try:
                    saved = json.loads(SETTINGS_PATH.read_text(encoding="utf-8"))
                except (ValueError, OSError):
                    saved = {}
            saved.update({
                "workspace_path": self.workspace.get().strip(),
                "nas_path": self.nas_path.get().strip(),
                "quickconnect_id": self.quickconnect_id.get().strip(),
            })
            payload = json.dumps(saved, ensure_ascii=False, indent=2)
            temporary = SETTINGS_PATH.with_name(f".{SETTINGS_PATH.name}.{os.getpid()}.tmp")
            temporary.write_text(payload, encoding="utf-8")
            os.replace(temporary, SETTINGS_PATH)
        except OSError as exc:
            self.log(f"设置保存失败：{exc}")

    @staticmethod
    def backend_command(kind: str, args: list[str]) -> tuple[list[str], dict[str, str]]:
        """Return a working backend command in portable and PyInstaller builds."""
        environment = os.environ.copy()
        environment["WORKSPACE_OS_ROOT"] = str(ROOT)
        if getattr(sys, "frozen", False):
            if not FROZEN_HELPER.is_file():
                raise FileNotFoundError(f"独立版后端助手不存在：{FROZEN_HELPER}")
            return [str(FROZEN_HELPER), kind, *args], environment
        script = CLI if kind == "cli" else SYNC_SERVER
        return [sys.executable, str(script), *args], environment

    def _build_style(self) -> None:
        style = ttk.Style(self)
        try:
            style.theme_use("clam")
        except tk.TclError:
            pass
        style.configure("Nexus.TFrame", background=BG)
        style.configure("Nexus.TLabel", background=BG, foreground=TEXT)

    def _build_ui(self) -> None:
        outer = tk.Frame(self, bg=BG, padx=26, pady=20)
        outer.pack(fill="both", expand=True)
        outer.columnconfigure(0, weight=1)
        outer.rowconfigure(2, weight=1)

        header = tk.Frame(outer, bg=BG)
        header.grid(row=0, column=0, sticky="ew", pady=(0, 15))
        header.columnconfigure(1, weight=1)
        logo = tk.Canvas(header, width=52, height=52, highlightthickness=0, bg=BG)
        logo.grid(row=0, column=0, rowspan=2, padx=(0, 14))
        logo.create_polygon(26, 2, 49, 15, 49, 38, 26, 50, 3, 38, 3, 15, fill=ACCENT_SOFT, outline="")
        logo.create_line(16, 38, 16, 17, 37, 38, 37, 17, fill=CYAN, width=4, capstyle="round", joinstyle="round")
        logo.create_oval(13, 14, 19, 20, fill=ACCENT, outline="")
        logo.create_oval(34, 14, 40, 20, fill=CYAN, outline="")
        logo.create_oval(34, 35, 40, 41, fill=CYAN, outline="")
        brand = tk.Frame(header, bg=BG)
        brand.grid(row=0, column=1, rowspan=2, sticky="w")
        tk.Label(brand, text="WORKSPACE OS 2.0", bg=BG, fg=ACCENT, font=("Helvetica Neue", 9, "bold")).pack(anchor="w")
        tk.Label(brand, text="NEXUS", bg=BG, fg=TEXT, font=("Helvetica Neue", 23, "bold")).pack(anchor="w", pady=(0, 1))
        tk.Label(brand, text="你的本地工作区与 NAS 控制中心", bg=BG, fg=MUTED, font=("Helvetica Neue", 10)).pack(anchor="w")
        status_group = tk.Frame(header, bg=BG)
        status_group.grid(row=0, column=2, rowspan=2, sticky="e")
        self.status_pill = tk.Frame(status_group, bg=GOOD_SOFT, padx=12, pady=6)
        self.status_pill.pack(anchor="e")
        self.status_label = tk.Label(
            self.status_pill, text="●  系统就绪", bg=GOOD_SOFT, fg=GOOD,
            font=("Helvetica Neue", 9, "bold"),
        )
        self.status_label.pack()
        tk.Label(
            status_group, text="本地优先  ·  手动同步", bg=BG, fg=MUTED,
            font=("Helvetica Neue", 8, "bold"),
        ).pack(anchor="e", pady=(6, 0))

        path_panel = self._panel(outer, row=1, pady=(0, 16))
        path_panel.columnconfigure(1, weight=1)
        label_group = tk.Frame(path_panel, bg=PANEL)
        label_group.grid(row=0, column=0, padx=(15, 14), pady=10, sticky="w")
        tk.Label(label_group, text="本地工作区", bg=PANEL, fg=TEXT, font=("Helvetica Neue", 10, "bold")).pack(anchor="w")
        tk.Label(label_group, text="当前使用位置", bg=PANEL, fg=MUTED, font=("Helvetica Neue", 8, "bold")).pack(anchor="w", pady=(2, 0))
        query_frame = tk.Frame(path_panel, bg=PANEL_SOFT)
        query_frame.grid(row=0, column=1, sticky="ew", pady=10)
        query_frame.columnconfigure(0, weight=1)
        tk.Entry(query_frame, textvariable=self.workspace, bg=PANEL_SOFT, fg=MUTED_STRONG, insertbackground=CYAN, relief="flat", bd=0, highlightthickness=0, font=("Helvetica Neue", 10)).grid(row=0, column=0, sticky="ew", padx=12, pady=8)
        self._button(path_panel, "选择目录", self.choose_workspace, width=92).grid(row=0, column=2, padx=9)
        self._button(path_panel, "打开网页版  ↗", self.open_dashboard, primary=True, width=126).grid(row=0, column=3, padx=(0, 10))

        body = tk.Frame(outer, bg=BG)
        body.grid(row=2, column=0, sticky="nsew")
        body.columnconfigure(0, weight=7)
        body.columnconfigure(1, weight=5)
        body.rowconfigure(0, weight=1)
        left = tk.Frame(body, bg=BG)
        left.grid(row=0, column=0, sticky="nsew", padx=(0, 16))
        left.columnconfigure(0, weight=1)
        for row in (1, 4, 5, 6):
            left.rowconfigure(row, weight=1, uniform="action-cards", minsize=76)
        right = tk.Frame(body, bg=BG)
        right.grid(row=0, column=1, sticky="nsew")
        right.columnconfigure(0, weight=1)
        right.rowconfigure(3, weight=1)

        self._section(left, 0, "常用操作", "QUICK ACTIONS")
        quick = self._button_row(left, 1, 3)
        self._card(quick, 0, "初始化工作区", "创建标准目录", lambda: self.run_cli("初始化工作区", ["init", "--path", self.workspace.get()]), "＋")
        self._card(quick, 1, "整理收件箱", "预览建议分类", lambda: self.run_workspace("扫描收件箱（预览）", ["scan-inbox"]), "⌁")
        self._card(quick, 2, "执行收件箱整理", "确认后移动文件", self.apply_inbox, "✓")

        search = self._panel(left, row=2, pady=(3, 15))
        search.columnconfigure(1, weight=1)
        tk.Label(search, text="⌕", bg=PANEL, fg=CYAN, font=("Helvetica Neue", 20, "bold")).grid(row=0, column=0, padx=(15, 9), pady=10)
        search_entry = tk.Entry(search, textvariable=self.search_query, bg=PANEL, fg=TEXT, insertbackground=CYAN, relief="flat", bd=0, highlightthickness=0, font=("Helvetica Neue", 12))
        search_entry.grid(row=0, column=1, sticky="ew", pady=10)
        search_entry.bind("<Return>", lambda _event: self.search())
        search_hint = tk.Label(
            search, text="搜索文件名、项目或关键词", bg=PANEL, fg=MUTED,
            font=("Helvetica Neue", 11), cursor="xterm",
        )
        search_hint.grid(row=0, column=1, sticky="w")
        search_hint.bind("<Button-1>", lambda _event: search_entry.focus_set())
        search_entry.bind("<FocusIn>", lambda _event: search_hint.grid_remove())
        search_entry.bind(
            "<FocusOut>",
            lambda _event: search_hint.grid() if not self.search_query.get().strip() else None,
        )
        self._button(search, "搜索资料", self.search, width=94).grid(row=0, column=2, padx=9, pady=8)

        self._section(left, 3, "系统与保护", "SYSTEM & RECOVERY")
        protection = self._button_row(left, 4, 3)
        self._card(protection, 0, "更新搜索索引", "收录新增和修改文件", lambda: self.run_workspace("更新搜索索引", ["search-maintain", "--database", str(self.index_db()), "--content", "--output", str(self.index_file("Search/search-status.json"))]), "⌕")
        self._card(protection, 1, "快照预览", "查看将要备份的内容", lambda: self.run_workspace("快照预览", ["snapshot", "--destination", str(self.snapshot_root()), "--exclude-rebuildable-cache"]), "◫")
        self._card(protection, 2, "创建快照", "保存当前可恢复副本", self.create_snapshot, "◆")
        maintenance = self._button_row(left, 5, 3)
        self._card(maintenance, 0, "系统健康检查", "检查工作区与 NAS", self.doctor, "●")
        self._card(maintenance, 1, "安全检查", "查看敏感信息风险", lambda: self.run_workspace("安全检查", ["security-audit"]), "◇")
        self._card(maintenance, 2, "提醒与告警", "查看需要处理的事项", lambda: self.run_workspace("提醒与告警", ["alerts"]), "!")
        recovery = self._button_row(left, 6, 3)
        self._card(recovery, 0, "恢复状态", "确认备份是否可恢复", self.recovery_readiness, "↻")
        self._card(recovery, 1, "恢复到新文件夹", "始终避免覆盖原资料", self.restore_snapshot, "⇩")
        self._card(recovery, 2, "打开工作区", "在 Finder 中查看文件", self.open_workspace, "↗")

        self._section(right, 0, "连接概览", "CONNECTIONS")
        storage = self._panel(right, row=1, pady=(0, 16))
        storage.columnconfigure(0, weight=1)
        self._storage_row(storage, 0, "电脑本地", self.workspace.get(), Path(self.workspace.get()).expanduser().is_dir())
        self._storage_row(storage, 1, "NAS", self.nas_path.get(), Path(self.nas_path.get()).expanduser().is_dir())
        separator = tk.Frame(storage, height=1, bg=LINE)
        separator.grid(row=2, column=0, sticky="ew", padx=14)
        links = tk.Frame(storage, bg=PANEL)
        links.grid(row=3, column=0, sticky="ew", padx=12, pady=11)
        self._button(links, "NAS 设置", self.configure_nas, width=92).pack(side="left")
        self._button(links, "QuickConnect", self.open_quickconnect, width=108).pack(side="left", padx=(8, 0))
        self._button(links, "使用说明", self.open_help, width=92).pack(side="left", padx=(8, 0))

        self._section(right, 2, "活动日志", "LIVE")
        log_frame = self._panel(right, row=3, pady=(0, 0))
        log_frame.columnconfigure(0, weight=1)
        log_frame.rowconfigure(1, weight=1)
        toolbar = tk.Frame(log_frame, bg=PANEL)
        toolbar.grid(row=0, column=0, sticky="ew", padx=14, pady=(11, 5))
        tk.Label(toolbar, text="最近记录", bg=PANEL, fg=MUTED_STRONG, font=("Helvetica Neue", 9, "bold")).pack(side="left")
        tk.Label(toolbar, text="仅保存在本机", bg=PANEL_SOFT, fg=MUTED, font=("Helvetica Neue", 8, "bold"), padx=8, pady=3).pack(side="right")
        self.log_box = tk.Text(log_frame, width=44, height=12, bg=PANEL_DARK, fg="#C7D0DF", insertbackground=CYAN, relief="flat", bd=0, highlightthickness=0, font=("Menlo", 9), wrap="word", padx=11, pady=9)
        self.log_box.grid(row=1, column=0, sticky="nsew", padx=10, pady=(3, 10))
        self.log_box.configure(state="disabled")

    def _panel(self, parent, row: int, pady=(0, 0)) -> tk.Frame:
        panel = tk.Frame(parent, bg=PANEL, bd=0, highlightthickness=0)
        panel.grid(row=row, column=0, sticky="nsew", pady=pady)
        return panel

    def _section(self, parent, row: int, text: str, english: str = "") -> None:
        bar = tk.Frame(parent, bg=BG)
        bar.grid(row=row, column=0, sticky="ew", pady=(0, 8))
        marker = tk.Frame(bar, bg=ACCENT, width=3, height=15)
        marker.pack(side="left", padx=(0, 9))
        marker.pack_propagate(False)
        tk.Label(bar, text=text, bg=BG, fg=TEXT, font=("Helvetica Neue", 12, "bold")).pack(side="left")

    def _button_row(self, parent, row: int, columns: int) -> tk.Frame:
        frame = tk.Frame(parent, bg=BG)
        frame.grid(row=row, column=0, sticky="nsew", pady=(0, 8))
        frame.rowconfigure(0, weight=1)
        for column in range(columns):
            frame.columnconfigure(column, weight=1)
        return frame

    def _button(
        self, parent, text: str, command: Callable[[], None], primary: bool = False,
        width: int | None = None,
    ) -> NexusButton:
        button = NexusButton(parent, text, command, primary=primary, compact=True, width=width)
        self.action_buttons.append(button)
        return button

    def _card(self, parent, column: int, title: str, subtitle: str, action: Callable[[], None], icon: str = "◇") -> None:
        button = NexusButton(
            parent, title, action, subtitle=subtitle, icon=icon, compact=False,
        )
        self.action_buttons.append(button)
        button.grid(row=0, column=column, sticky="nsew", padx=(0 if column == 0 else 8, 0))

    def _storage_row(self, parent, row: int, title: str, path: str, available: bool) -> None:
        item = tk.Frame(parent, bg=PANEL, padx=14, pady=11)
        item.grid(row=row, column=0, sticky="ew")
        item.columnconfigure(0, weight=1)
        tk.Label(item, text=title, bg=PANEL, fg=TEXT, font=("Helvetica Neue", 11, "bold")).grid(row=0, column=0, sticky="w")
        status_bg = GOOD_SOFT if available else WARN_SOFT
        status_fg = GOOD if available else WARN
        tk.Label(
            item, text="●  在线" if available else "●  离线", bg=status_bg, fg=status_fg,
            font=("Helvetica Neue", 8, "bold"), padx=8, pady=3,
        ).grid(row=0, column=1, sticky="e")
        tk.Label(item, text=path, bg=PANEL, fg=MUTED, font=("Helvetica Neue", 9), anchor="w", justify="left", wraplength=340).grid(row=1, column=0, columnspan=2, sticky="ew", pady=(5, 0))

    def workspace_args(self, args: list[str]) -> list[str]:
        return [args[0], "--workspace", self.workspace.get().strip(), *args[1:]]

    def snapshot_root(self) -> Path:
        return Path(self.workspace.get()).expanduser().parent / "WorkspaceSnapshots"

    def index_db(self) -> Path:
        return self.index_file("Search/workspace-search.db")

    def index_file(self, name: str) -> Path:
        return Path(self.workspace.get()).expanduser() / "08_Indexes" / name

    def search_db_for_read(self) -> Path:
        """Prefer the canonical index while preserving access to a legacy Mac index."""
        canonical = self.index_db()
        legacy = self.index_file("workspace-search.db")
        return canonical if canonical.is_file() or not legacy.is_file() else legacy

    def choose_workspace(self) -> None:
        choice = filedialog.askdirectory(initialdir=self.workspace.get() or str(Path.home()))
        if choice:
            self.workspace.set(choice)
            self.save_settings()
            self.log(f"工作区已保存：{choice}")

    def configure_nas(self) -> None:
        current = Path(self.nas_path.get()).expanduser()
        initial = current if current.is_dir() else Path("/Volumes")
        value = filedialog.askdirectory(
            title="选择已挂载的 NAS 目录（例如 /Volumes/Workspace）",
            initialdir=str(initial), parent=self,
        )
        if value:
            self.nas_path.set(value)
            self.save_settings()
            self.log(f"NAS 路径已保存：{value}")

    def open_quickconnect(self) -> None:
        """Open DSM via QuickConnect; credentials stay in the browser/DSM."""
        from tkinter import simpledialog
        raw = simpledialog.askstring(
            "QuickConnect 登录",
            "输入或修改群晖 QuickConnect ID（不输入密码）：",
            initialvalue=self.quickconnect_id.get().strip(),
            parent=self,
        ) or ""
        if not raw.strip():
            self.log("QuickConnect 登录已取消；原 ID 保持不变。")
            return
        try:
            quickconnect_id = normalize_quickconnect_id(raw)
        except ValueError as exc:
            messagebox.showerror("QuickConnect", str(exc), parent=self)
            return
        self.quickconnect_id.set(quickconnect_id)
        self.save_settings()
        url = f"https://quickconnect.to/{quickconnect_id}"
        try:
            with self.child_process_lock:
                process = subprocess.Popen(["open", url], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                self.child_processes.add(process)
            threading.Thread(target=self._reap_child, args=(process,), daemon=True).start()
            self.log(f"已打开 QuickConnect：{url}；请在 DSM 中进入 File Station，再打开 Workspace。")
        except OSError as exc:
            self.log(f"QuickConnect 打开失败：{exc}")
            messagebox.showerror("QuickConnect", f"无法打开浏览器：{exc}", parent=self)

    def _reap_child(self, process: subprocess.Popen[str]) -> None:
        try:
            process.wait(timeout=30)
        except (OSError, subprocess.TimeoutExpired):
            pass
        finally:
            with self.child_process_lock:
                self.child_processes.discard(process)

    def resolved_nas_path(self) -> str:
        """Use the configured mount first, then a uniquely identifiable mounted Workspace."""
        configured = Path(self.nas_path.get().strip()).expanduser()
        try:
            if configured.is_dir():
                return str(configured)
        except OSError:
            pass
        candidates: list[Path] = []
        volumes = Path("/Volumes")
        try:
            for candidate in volumes.iterdir():
                if candidate == configured or candidate.name.startswith("Workspace OS 2.0 NEXUS"):
                    continue
                try:
                    if candidate.is_dir() and (candidate / ".workspace-os.json").is_file():
                        candidates.append(candidate)
                except OSError:
                    continue
        except OSError:
            pass
        if len(candidates) == 1:
            actual = str(candidates[0])
            self.log(f"NAS 配置路径不可用：{configured}")
            self.log(f"临时使用已挂载 Workspace：{actual}；可在“NAS 设置”中保存最终路径。")
            return actual
        return str(configured)

    def set_busy(self, busy: bool) -> None:
        self.busy_count = max(0, self.busy_count + (1 if busy else -1))
        state = "disabled" if self.busy_count else "normal"
        if self.busy_count:
            self._set_status("●  正在处理", ACCENT_HOVER, ACCENT_SOFT)
        for button in self.action_buttons:
            try:
                button.configure(state=state)
            except tk.TclError:
                pass

    def _set_status(self, text: str, foreground: str, background: str, reset_after: int = 0) -> None:
        if self.status_reset_job:
            self.after_cancel(self.status_reset_job)
            self.status_reset_job = None
        self.status_pill.configure(bg=background)
        self.status_label.configure(text=text, bg=background, fg=foreground)
        if reset_after:
            self.status_reset_job = self.after(reset_after, self._reset_status)

    def _reset_status(self) -> None:
        self.status_reset_job = None
        if not self.busy_count:
            self._set_status("●  系统就绪", GOOD, GOOD_SOFT)

    def log(self, text: str) -> None:
        self.log_box.configure(state="normal")
        for line in str(text).splitlines() or [""]:
            self.log_box.insert("end", f"[{dt.datetime.now():%H:%M:%S}] {line}\n")
        self.log_box.see("end")
        self.log_box.configure(state="disabled")

    def run_cli(self, title: str, args: list[str], on_complete: Callable[[str], None] | None = None) -> None:
        self.save_settings()
        self.set_busy(True)
        self.log(f"开始：{title}")

        def worker() -> None:
            process: subprocess.Popen[str] | None = None
            try:
                command, environment = self.backend_command("cli", args)
                process = subprocess.Popen(
                    command, cwd=ROOT, env=environment,
                    stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                    text=True, encoding="utf-8", errors="replace",
                )
                with self.child_process_lock:
                    self.child_processes.add(process)
                stdout, stderr = process.communicate()
                output = stdout.strip()
                error = stderr.strip()
                returncode = int(process.returncode or 0)
                self.after(0, lambda: self.finish(title, returncode, output, error, on_complete))
            except Exception as exc:
                message = str(exc)
                self.after(0, lambda: self.finish(title, 2, "", message, on_complete))
            finally:
                if process is not None:
                    with self.child_process_lock:
                        self.child_processes.discard(process)
        threading.Thread(target=worker, daemon=True).start()

    def run_workspace(self, title: str, args: list[str], on_complete: Callable[[str], None] | None = None) -> None:
        self.run_cli(title, self.workspace_args(args), on_complete)

    def finish(self, title: str, code: int, output: str, error: str, on_complete: Callable[[str], None] | None) -> None:
        self.set_busy(False)
        if output:
            self.log(output)
        if error:
            self.log("提示：" + error)
        if code == 0:
            self.log(f"完成：{title}")
            self._set_status("●  操作已完成", GOOD, GOOD_SOFT, reset_after=3000)
            if on_complete:
                try:
                    on_complete(output)
                except Exception as exc:
                    self.log(f"后续操作失败：{exc}")
        else:
            self.log(f"失败：{title}（退出码 {code}）")
            self._set_status("●  操作失败", WARN, WARN_SOFT)
            messagebox.showerror("Workspace OS", f"{title}失败。\n\n{error or output or '请查看活动日志。'}", parent=self)

    def apply_inbox(self) -> None:
        if messagebox.askyesno("Workspace OS", "确认执行收件箱整理？\n\n文件会按照预览计划移动，并保留操作日志。", parent=self):
            self.run_workspace("执行收件箱整理", ["scan-inbox", "--apply"])

    def create_snapshot(self) -> None:
        if messagebox.askyesno("Workspace OS", f"确认创建可恢复快照？\n\n保存位置：{self.snapshot_root()}", parent=self):
            self.run_workspace("创建快照", ["snapshot", "--destination", str(self.snapshot_root()), "--exclude-rebuildable-cache", "--apply"])

    def doctor(self) -> None:
        self.run_workspace(
            "系统健康检查",
            [
                "doctor", "--snapshots", str(self.snapshot_root()),
                "--nas", self.resolved_nas_path(),
                "--output", str(self.index_file("Health/workspace-health.json")),
            ],
        )

    def recovery_readiness(self) -> None:
        self.run_workspace(
            "恢复状态",
            [
                "recovery-readiness", "--snapshots", str(self.snapshot_root()),
                "--output", str(self.index_file("Recovery/recovery-readiness.json")),
            ],
        )

    def restore_snapshot(self) -> None:
        snapshot = filedialog.askdirectory(title="选择要恢复的快照", initialdir=str(self.snapshot_root()))
        if not snapshot:
            return
        destination = filedialog.askdirectory(title="选择恢复目标目录（建议新建空目录）", initialdir=str(Path(self.workspace.get()).expanduser().parent))
        if not destination:
            return
        if not messagebox.askyesno("Workspace OS", f"确认恢复到新目录？\n\n快照：{snapshot}\n目标：{destination}\n\n不会覆盖现有文件。", parent=self):
            return
        self.run_cli("恢复快照", ["restore", snapshot, "--destination", destination, "--apply"])

    def search(self) -> None:
        query = self.search_query.get().strip()
        if not query:
            messagebox.showinfo("Workspace OS 搜索", "请输入搜索关键词。", parent=self)
            return

        def show_results(output: str) -> None:
            try:
                data = json.loads(output)
                rows = data.get("results", [])
            except (json.JSONDecodeError, AttributeError):
                messagebox.showerror("Workspace OS 搜索", "搜索结果格式无法读取，请查看活动日志。", parent=self)
                return
            if not rows:
                messagebox.showinfo("Workspace OS 搜索", f"没有找到与 [{query}] 相关的文件。", parent=self)
                return
            preview = "\n".join(f"• {row.get('name', '')}  —  {row.get('path', '')}" for row in rows[:12])
            messagebox.showinfo("Workspace OS 搜索结果", f"找到 {len(rows)} 个结果：\n\n{preview}", parent=self)

        self.run_cli("搜索：" + query, ["search", query, "--database", str(self.search_db_for_read()), "--limit", "50"], show_results)

    @staticmethod
    def free_port() -> int:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
            listener.bind(("127.0.0.1", 0))
            return int(listener.getsockname()[1])

    def stop_dashboard(self) -> None:
        process = self.dashboard_process
        self.dashboard_process = None
        if process and process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=3)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=3)
        if self.dashboard_log_handle:
            self.dashboard_log_handle.close()
            self.dashboard_log_handle = None

    def stop_stale_dashboard_servers(self, dashboard: Path) -> None:
        """Remove orphaned services left by an older or crashed control center."""
        if sys.platform != "darwin":
            return
        try:
            listing = subprocess.run(
                ["ps", "-axo", "pid=,uid=,command="], capture_output=True, text=True,
                encoding="utf-8", errors="replace", timeout=3, check=True,
            ).stdout
        except (OSError, subprocess.SubprocessError):
            return
        marker = f"--dashboard {dashboard}"
        stopped = 0
        for line in listing.splitlines():
            fields = line.strip().split(None, 2)
            if len(fields) != 3:
                continue
            try:
                pid, uid = int(fields[0]), int(fields[1])
            except ValueError:
                continue
            command = fields[2]
            is_sync_service = (
                "dashboard_sync_server.py" in command
                or "WorkspaceOSHelper server" in command
            )
            if uid != os.getuid() or pid == os.getpid() or not is_sync_service or marker not in command:
                continue
            try:
                os.kill(pid, signal.SIGTERM)
                stopped += 1
            except (OSError, ProcessLookupError):
                pass
        if stopped:
            self.log(f"已清理 {stopped} 个旧版网页服务，避免连接到过期配置。")

    def start_dashboard_server(self, _output: str, workspace: str, nas: str, dashboard: Path) -> None:
        if not dashboard.is_file():
            self.dashboard_failed("当前版本的临时看板没有生成，已停止打开网页版。")
            return
        self.stop_dashboard()
        self.stop_stale_dashboard_servers(dashboard)
        port = self.free_port()
        try:
            command, environment = self.backend_command("server", [
                "--computer", workspace, "--nas", nas,
                "--dashboard", str(dashboard), "--port", str(port),
            ])
            LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
            self.dashboard_log_handle = LOG_PATH.open("a", encoding="utf-8")
            self.dashboard_process = subprocess.Popen(
                command, cwd=ROOT, env=environment, stdout=self.dashboard_log_handle,
                stderr=subprocess.STDOUT, text=True, encoding="utf-8", errors="replace",
            )
            threading.Thread(
                target=self.wait_for_dashboard,
                args=(port, dashboard, self.dashboard_process), daemon=True,
            ).start()
        except Exception as exc:
            self.dashboard_failed(str(exc))

    def wait_for_dashboard(self, port: int, dashboard: Path, process: subprocess.Popen[str]) -> None:
        health = f"http://127.0.0.1:{port}/api/health"
        reason = "同步服务启动超时"
        for _ in range(50):
            if process.poll() is not None:
                reason = f"同步服务已退出（代码 {process.returncode}）；日志：{LOG_PATH}"
                break
            try:
                with urllib.request.urlopen(health, timeout=0.5) as response:
                    if response.status == 200:
                        url = f"http://127.0.0.1:{port}/dashboard#compare"
                        self.after(0, lambda: self.dashboard_ready(url))
                        return
            except OSError:
                pass
            time.sleep(0.1)
        self.after(0, lambda: self.dashboard_failed(reason))

    def dashboard_ready(self, url: str) -> None:
        subprocess.Popen(["open", url])
        self.log("网页版已启用左右对比和后台同步。")

    def dashboard_failed(self, reason: str) -> None:
        self.stop_dashboard()
        self.log(f"网页版启动失败，未打开旧缓存页面：{reason}")
        messagebox.showerror(
            "Workspace OS",
            f"网页版生成或同步服务启动失败。为避免加载旧模板，本次已停止。\n\n{reason}\n\n日志：{LOG_PATH}",
            parent=self,
        )

    def open_dashboard(self) -> None:
        workspace = self.workspace.get().strip()
        nas = self.resolved_nas_path()
        if not workspace or not nas:
            messagebox.showinfo("Workspace OS", "请先配置工作区和 NAS 路径。", parent=self)
            return
        if not Path(workspace).expanduser().is_dir():
            messagebox.showinfo("Workspace OS", "工作区目录不存在，请先初始化或选择目录。", parent=self)
            return
        if not Path(nas).expanduser().is_dir():
            messagebox.showinfo("Workspace OS", "NAS 尚未挂载，请先在 Finder 中连接服务器。", parent=self)
            return
        DASHBOARD_RUNTIME_DIR.mkdir(parents=True, exist_ok=True)
        dashboard = DASHBOARD_RUNTIME_DIR / "file-locations.html"
        indexes = Path(workspace).expanduser() / "08_Indexes"
        arguments = [
            "locations", "--computer", workspace, "--nas", nas,
            "--output", str(dashboard), "--refresh-nas-capacity",
        ]
        # Use current-version runtime data first, then the workspace JSON only as a
        # metadata cache. The HTML itself is always rebuilt from this app's template.
        runtime_cache = dashboard.with_suffix(".json")
        workspace_cache = self.index_file("file-locations.json")
        cache = runtime_cache if runtime_cache.is_file() else workspace_cache
        if cache.is_file():
            arguments.extend(["--nas-cache", str(cache)])
        else:
            arguments.append("--refresh-nas")
        # Freeze the previous local service before regenerating shared reports and
        # runtime HTML so another open tab cannot overwrite this refresh chain.
        self.stop_dashboard()
        self.stop_stale_dashboard_servers(dashboard)
        self.run_cli(
            "刷新网页版健康状态",
            [
                "doctor", "--workspace", workspace,
                "--snapshots", str(Path(workspace).expanduser().parent / "WorkspaceSnapshots"),
                "--nas", nas,
                "--output", str(indexes / "Health" / "workspace-health.json"),
            ],
            lambda _health: self.run_cli(
                "刷新网页版告警",
                [
                    "alerts", "--workspace", workspace,
                    "--output", str(indexes / "Alerts" / "control-plane.json"),
                ],
                lambda _alerts: self.run_cli(
                    "刷新网页版 Workspace OS", arguments,
                    lambda output: self.start_dashboard_server(output, workspace, nas, dashboard),
                ),
            ),
        )

    def open_workspace(self) -> None:
        path = Path(self.workspace.get()).expanduser()
        if path.is_dir():
            subprocess.Popen(["open", str(path)])
        else:
            messagebox.showinfo("Workspace OS", "工作区目录不存在，请先初始化或选择目录。", parent=self)

    def open_help(self) -> None:
        if HELP_FILE.is_file():
            subprocess.Popen(["open", str(HELP_FILE)])
        else:
            messagebox.showinfo("Workspace OS", "使用说明文件不存在。", parent=self)

    def close_app(self) -> None:
        self.save_settings()
        self.stop_dashboard()
        with self.child_process_lock:
            children = list(self.child_processes)
        for process in children:
            if process.poll() is None:
                process.terminate()
        for process in children:
            try:
                process.wait(timeout=3)
            except subprocess.TimeoutExpired:
                process.kill()
        self.destroy()


if __name__ == "__main__":
    if sys.platform != "darwin":
        print("This graphical control center is intended for macOS.", file=sys.stderr)
    if not CLI.is_file() or not SYNC_SERVER.is_file():
        raise SystemExit(f"Workspace OS core files are missing under: {ROOT}")
    WorkspaceOSApp().mainloop()
