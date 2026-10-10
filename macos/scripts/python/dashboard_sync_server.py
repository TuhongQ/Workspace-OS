"""Local-only NEXUS sync API: copy selected one-sided files with progress."""
from __future__ import annotations

import argparse
import ctypes
import errno
import sys
import json
import os
import shutil
import socket
import subprocess
import threading
import time
import uuid
from datetime import datetime, timezone
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path, PurePosixPath, PureWindowsPath
from typing import Any
from urllib.parse import parse_qs, urlparse, unquote

from alert_center import build_alert_center, save_alert_center
from health import save_health, workspace_health
from location_snapshot import build_location_snapshot, save_location_snapshot
from path_safety import is_link_or_reparse


def _under(root: Path, candidate: Path) -> bool:
    try:
        resolved_root = Path(root).expanduser().resolve(strict=False)
        resolved_candidate = Path(candidate).expanduser().resolve(strict=False)
        return os.path.commonpath([resolved_root, resolved_candidate]) == str(resolved_root)
    except (OSError, ValueError):
        return False


SKIP_PARTS = {
    "#recycle", "@eadir", "$recycle.bin", ".git", ".vs", "__pycache__",
    ".pytest_cache", "node_modules", ".venv", ".ds_store", ".spotlight-v100", ".fseventsd", ".trashes",
}


def _safe_relative(value: Any, *, allow_empty: bool = False) -> str:
    if not isinstance(value, str):
        raise ValueError("文件路径不安全")
    raw = value.strip()
    normalized = raw.replace("\\", "/")
    if not normalized:
        if allow_empty:
            return ""
        raise ValueError("文件路径不能为空")
    if (
        normalized.startswith("/")
        or PurePosixPath(normalized).is_absolute()
        or PureWindowsPath(raw).is_absolute()
        or "\x00" in normalized
    ):
        raise ValueError("文件路径不安全")
    parts = PurePosixPath(normalized).parts
    if not parts or any(part in {"", ".", ".."} for part in parts):
        raise ValueError("文件路径不安全")
    lowered = [part.casefold() for part in parts]
    if lowered[0] == "08_indexes" or any(part in SKIP_PARTS for part in lowered):
        raise ValueError("该路径不属于可同步范围")
    return PurePosixPath(*parts).as_posix()


def _contains_link(root: Path, candidate: Path) -> bool:
    """Reject every existing link component, even when it resolves inside root."""
    lexical_root = Path(os.path.abspath(os.path.expanduser(str(root))))
    lexical_candidate = Path(os.path.abspath(os.path.expanduser(str(candidate))))
    try:
        parts = lexical_candidate.relative_to(lexical_root).parts
    except ValueError:
        return True
    current = lexical_root
    for part in parts:
        current /= part
        try:
            if current.exists() and is_link_or_reparse(current):
                return True
        except OSError:
            return True
    return False


def _covered_by_prefix(relative: str, prefixes: list[str]) -> bool:
    return any(relative == prefix or relative.startswith(prefix.rstrip("/") + "/") for prefix in prefixes)


def _path_available_quick(path: Path, timeout_seconds: int = 5) -> tuple[bool, str]:
    """Avoid hanging worker threads forever on a reconnecting SMB drive."""
    path_text = str(path)
    if os.name == "nt" and path_text.startswith("\\\\"):
        host = path_text.strip("\\").split("\\", 1)[0]
        try:
            with socket.create_connection((host, 445), timeout=timeout_seconds):
                pass
            return True, ""
        except OSError as exc:
            return False, f"NAS 主机 {host}:445 不可连接：{exc}"
    try:
        return path.exists(), "" if path.exists() else f"路径 {path} 当前不可访问"
    except OSError as exc:
        return False, str(exc)


def _target_writable_quick(path: Path, timeout_seconds: int = 5) -> tuple[bool, str]:
    if os.name == "nt" and str(path).startswith("\\\\"):
        return True, ""
    try:
        test_path = path / f".workspace-os-write-test-{uuid.uuid4().hex}.tmp"
        test_path.write_text("ok", encoding="utf-8")
        test_path.unlink(missing_ok=True)
        return True, ""
    except OSError as exc:
        return False, str(exc)


class SyncJobs:
    """In-memory, non-destructive copy jobs bound to exactly two configured roots."""

    def __init__(self, computer: Path, nas: Path, dashboard: Path) -> None:
        self.computer = Path(os.path.abspath(os.path.expanduser(str(computer))))
        self.nas = Path(os.path.abspath(os.path.expanduser(str(nas))))
        self.dashboard = Path(os.path.abspath(os.path.expanduser(str(dashboard))))
        self.jobs_path = self.dashboard.with_name(self.dashboard.stem + ".sync-jobs.json")
        self.jobs: dict[str, dict[str, Any]] = self._load_jobs()
        self.lock = threading.Lock()
        self.snapshot_lock = threading.RLock()
        self.transfer_lock = threading.Lock()
        self.last_preserved_log = ""
        self._last_persist = 0.0

    def _load_jobs(self) -> dict[str, dict[str, Any]]:
        try:
            raw = json.loads(self.jobs_path.read_text(encoding="utf-8"))
            items = raw.get("jobs", []) if isinstance(raw, dict) else []
            jobs = {str(item["id"]): item for item in items if isinstance(item, dict) and item.get("id")}
            for item in jobs.values():
                if item.get("status") in {"queued", "scanning", "running"}:
                    item["status"] = "interrupted"
                    item["current"] = "服务重启，未完成文件需重新传输（已完成文件保留）"
            return jobs
        except (OSError, UnicodeDecodeError, json.JSONDecodeError, TypeError, KeyError):
            return {}

    def _persist_jobs_locked(self, *, force: bool = False) -> None:
        now = time.monotonic()
        if not force and now - self._last_persist < 0.5:
            return
        items = sorted(self.jobs.values(), key=lambda item: item.get("created_at", ""), reverse=True)[:20]
        temporary = self.jobs_path.with_name(self.jobs_path.name + ".partial")
        try:
            self.jobs_path.parent.mkdir(parents=True, exist_ok=True)
            temporary.write_text(json.dumps({"jobs": items}, ensure_ascii=False, indent=2), encoding="utf-8")
            os.replace(temporary, self.jobs_path)
            self._last_persist = now
        except OSError:
            try: temporary.unlink(missing_ok=True)
            except OSError: pass

    def _snapshot(self, *, live_nas: bool = False, transferred: list[str] | None = None) -> dict[str, Any]:
        with self.snapshot_lock:
            return self._snapshot_locked(live_nas=live_nas, transferred=transferred)

    def _snapshot_locked(self, *, live_nas: bool = False, transferred: list[str] | None = None) -> dict[str, Any]:
        previous_path = self.dashboard.with_suffix(".json")
        previous = None
        try:
            previous = json.loads(previous_path.read_text(encoding="utf-8-sig"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError):
            pass
        # Refresh only NAS paths actually copied. Reusing the old NAS cache
        # unchanged made successful uploads continue to appear as missing.
        if transferred and not live_nas:
            previous = previous or {"files": [], "directories": []}
            records = {item["relative"]: item for item in previous.get("files", [])}
            directories = {item["relative"]: item for item in previous.get("directories", [])}
            for relative in transferred:
                path = self.nas / relative
                stat = path.stat()
                if path.is_dir():
                    directories.setdefault(relative, {"relative": relative})["nas"] = True
                    continue
                record = records.setdefault(relative, {"relative": relative})
                record["nas"] = {
                    "path": str(path), "parent": str(path.parent), "size": stat.st_size,
                    "modified": datetime.fromtimestamp(stat.st_mtime, timezone.utc).isoformat(),
                    "modified_ns": stat.st_mtime_ns,
                }
                # Force comparison again instead of retaining the previous state.
                record.pop("computer", None)
                parent = Path(relative).parent
                while str(parent) != ".":
                    key = parent.as_posix()
                    directories.setdefault(key, {"relative": key})["nas"] = True
                    parent = parent.parent
            previous["files"] = list(records.values())
            previous["directories"] = list(directories.values())
        health_output = self.computer / "08_Indexes" / "Health" / "workspace-health.json"
        save_health(workspace_health(self.computer, self.computer.parent / "WorkspaceSnapshots", self.nas), health_output)
        save_alert_center(build_alert_center(self.computer), self.computer / "08_Indexes" / "Alerts" / "control-plane.json")
        snapshot = build_location_snapshot(
            self.computer, self.nas, previous=previous, reuse_previous_nas=not live_nas,
            refresh_nas_storage=live_nas,
        )
        save_location_snapshot(snapshot, self.dashboard)
        return snapshot

    def refresh_snapshot(self, *, live_nas: bool = False) -> dict[str, Any]:
        """Re-scan both configured roots and replace the dashboard data."""
        snapshot = self._snapshot(live_nas=live_nas)
        result = {
            "ok": True,
            "files": len(snapshot.get("files", [])),
            "refreshed_at": datetime.now(timezone.utc).isoformat(),
        }
        if live_nas:
            try:
                self.publish_dashboard()
                result["published"] = True
            except OSError as exc:
                result["publish_error"] = str(exc)
        return result

    def publish_dashboard(self) -> None:
        """Explicit refresh publishes only generated NEXUS artifacts."""
        with self.snapshot_lock:
            for root in (self.computer, self.nas):
                output = root / "08_Indexes"
                if not root.is_dir() or _contains_link(root, output):
                    raise OSError(f"看板目标不可访问：{output}")
                output.mkdir(exist_ok=True)
                for suffix in (".html", ".json"):
                    source = self.dashboard.with_suffix(suffix)
                    target = output / ("file-locations" + suffix)
                    if _contains_link(root, target):
                        raise OSError("看板目标为链接，已停止")
                    if source == target:
                        continue
                    temporary = output / f".nexus-{uuid.uuid4().hex}{suffix}"
                    try:
                        with temporary.open("xb") as handle:
                            handle.write(source.read_bytes())
                            handle.flush()
                            os.fsync(handle.fileno())
                        os.replace(temporary, target)
                    finally:
                        temporary.unlink(missing_ok=True)

    def _append_obsidian_sync_log(self, job: dict[str, Any], transferred: list[str]) -> str:
        """Append a small, conflict-safe summary to the NAS system log."""
        now = datetime.now().astimezone()
        log_path = self.nas / "09_System" / "SystemLog" / "WorkspaceOS" / f"sync-{now:%Y-%m-%d}.log"
        if not self.nas.is_dir() or _contains_link(self.nas, log_path):
            raise OSError("NAS 日志目标不可访问或包含链接")
        log_path.parent.mkdir(parents=True, exist_ok=True)
        direction = "上传到 NAS" if job.get("direction") == "to_nas" else "下载到电脑"
        mode = "覆盖" if job.get("mode") == "overwrite" else "同步"
        errors = len(job.get("errors") or [])
        files = list(dict.fromkeys(str(item).replace("\\", "/") for item in transferred))
        shown = "、".join(files[:12]) + (f" 等 {len(files)} 个文件" if len(files) > 12 else "")
        entry = (f"\n### {now:%H:%M}｜网页{mode}{direction}\n\n"
                 f"- 文件数量：{len(files)}\n- 传输结果：{'完成' if not errors else f'完成，{errors} 个失败'}\n"
                 f"- 文件清单：{shown or '无文件（可能为空文件夹）'}\n")
        # One append operation preserves entries written by other devices.
        with self.lock:
            with log_path.open("a+", encoding="utf-8", newline="") as handle:
                handle.seek(0, os.SEEK_END)
                header = f"# {now:%Y-%m-%d}\n\n## 工作日志\n" if handle.tell() == 0 else ""
                handle.write(header + entry)
                handle.flush()
                os.fsync(handle.fileno())
        return str(log_path)

    def _pull_obsidian_log_to_local(self, nas_log_path: str) -> str:
        """Keep a recoverable local copy before pulling an authoritative NAS note."""
        source = Path(nas_log_path)
        if not _under(self.nas, source) or _contains_link(self.nas, source):
            raise OSError("NAS 日志路径不安全")
        target = self.computer / source.relative_to(self.nas)
        if not _under(self.computer, target) or _contains_link(self.computer, target):
            raise OSError("本地日志路径不安全")
        target.parent.mkdir(parents=True, exist_ok=True)
        with self.snapshot_lock:
            content = source.read_bytes()
            self.last_preserved_log = ""
            if target.exists():
                local = target.read_bytes()
                if local == content:
                    return str(target)
                # Preserve every divergent version; do not infer that matching
                # headings imply the local note has already been merged.
                backup = target.with_name(f"{target.stem}.local-before-nas-{uuid.uuid4().hex[:12]}{target.suffix}")
                with backup.open("xb") as handle:
                    handle.write(local)
                self.last_preserved_log = str(backup)
            temporary = target.with_name(f".{target.name}.{uuid.uuid4().hex}.nas-sync.tmp")
            try:
                with temporary.open("xb") as handle:
                    handle.write(content)
                    handle.flush()
                    os.fsync(handle.fileno())
                os.replace(temporary, target)
            finally:
                temporary.unlink(missing_ok=True)
        return str(target)

    def _open_directory(self, candidate: Path) -> dict[str, Any]:
        if candidate.is_file():
            candidate = candidate.parent
        roots = (self.computer, self.nas)
        root = next((item for item in roots if _under(item, candidate)), None)
        if root is None or _contains_link(root, candidate):
            raise ValueError("目录不在已配置的 Workspace 或 NAS 范围内")
        if not candidate.is_dir():
            raise ValueError("目录不存在或当前不可访问")
        if os.name == "nt":
            os.startfile(str(candidate))  # type: ignore[attr-defined]
        elif sys.platform == "darwin":
            subprocess.Popen(["open", str(candidate)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        else:
            subprocess.Popen(["xdg-open", str(candidate)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return {"ok": True}

    def open_folder(self, side: Any, relative: Any) -> dict[str, Any]:
        if side not in {"computer", "nas"}:
            raise ValueError("目录侧无效")
        safe = _safe_relative(relative, allow_empty=True)
        root = self.computer if side == "computer" else self.nas
        return self._open_directory(root if not safe else root / safe)

    def open_folder_path(self, value: Any) -> dict[str, Any]:
        if not isinstance(value, str) or not value.strip():
            raise ValueError("目录路径不能为空")
        value = unquote(urlparse(value).path) if value.startswith("file://") else value
        candidate = Path(os.path.abspath(os.path.expanduser(value.strip())))
        if candidate.is_file():
            candidate = candidate.parent
        return self._open_directory(candidate)

    def _source_entries_from_prefixes(self, source_root: Path, prefixes: list[str]) -> dict[str, dict[str, Any]]:
        entries: dict[str, dict[str, Any]] = {}
        for prefix in prefixes:
            directory = source_root / prefix
            if _contains_link(source_root, directory) or not _under(source_root, directory) or not directory.is_dir() or is_link_or_reparse(directory):
                continue
            for current, dirnames, filenames in os.walk(directory):
                current_path = Path(current)
                dirnames[:] = [
                    name for name in dirnames
                    if name.lower() not in SKIP_PARTS
                    and not is_link_or_reparse(current_path / name)
                ]
                for name in filenames:
                    if name.lower() in SKIP_PARTS:
                        continue
                    path = current_path / name
                    try:
                        if is_link_or_reparse(path):
                            continue
                        stat = path.stat()
                        relative = path.relative_to(source_root).as_posix()
                    except (OSError, ValueError):
                        continue
                    if relative.lower().startswith("08_indexes/"):
                        continue
                    entries[relative] = {"relative": relative, "size": stat.st_size}
        return entries

    def _source_entries_from_relatives(
        self, source_root: Path, relatives: list[str], mode: str, snapshot: dict[str, Any] | None
    ) -> dict[str, dict[str, Any]]:
        entries: dict[str, dict[str, Any]] = {}
        expected = None
        if mode == "safe":
            expected = "COMPUTER_ONLY" if source_root == self.computer else "NAS_ONLY"
        snapshot_items = {
            item["relative"]: item
            for item in (snapshot or {}).get("files", [])
            if isinstance(item, dict) and item.get("relative")
        }
        for relative in relatives:
            path = source_root / relative
            try:
                if not _contains_link(source_root, path) and _under(source_root, path) and path.is_file() and not is_link_or_reparse(path):
                    entries[relative] = {"relative": relative, "size": path.stat().st_size}
            except OSError:
                continue
        return entries

    def start(
        self, direction: str, relatives: list[str] | None = None, prefixes: list[str] | None = None,
        mode: str = "safe",
    ) -> dict[str, Any]:
        if direction not in {"to_nas", "to_computer"}:
            raise ValueError("未知同步方向")
        if mode not in {"safe", "overwrite"}:
            raise ValueError("未知同步模式")
        selected = list(dict.fromkeys(_safe_relative(item) for item in (relatives or [])))
        selected_prefixes = list(dict.fromkeys(_safe_relative(item) for item in (prefixes or [])))
        selected_prefixes = [
            prefix for prefix in selected_prefixes
            if not any(prefix != other and prefix.startswith(other.rstrip("/") + "/") for other in selected_prefixes)
        ]
        if not selected and not selected_prefixes:
            raise ValueError("请选择文件或文件夹")
        if len(selected) + len(selected_prefixes) > 5000:
            raise ValueError("一次同步的项目过多，请分批执行")
        job_id = uuid.uuid4().hex
        job = {"id": job_id, "direction": direction, "mode": mode, "status": "queued",
               "total_files": len(selected) + len(selected_prefixes),
               "completed_files": 0, "total_bytes": 0, "copied_bytes": 0,
               "current": "", "errors": [], "created_at": datetime.now(timezone.utc).isoformat()}
        with self.lock:
            self.jobs[job_id] = job
            self._persist_jobs_locked(force=True)
        threading.Thread(target=self._run, args=(job_id, direction, selected, selected_prefixes, mode), daemon=True).start()
        return self.status(job_id)

    def status(self, job_id: str) -> dict[str, Any]:
        with self.lock:
            job = self.jobs.get(job_id)
            if not job:
                raise KeyError(job_id)
            total_files = int(job.get("total_files") or 0)
            total_bytes = int(job.get("total_bytes") or 0)
            if total_files:
                job["completed_files"] = min(int(job.get("completed_files") or 0), total_files)
            if total_bytes:
                job["copied_bytes"] = min(int(job.get("copied_bytes") or 0), total_bytes)
            self._persist_jobs_locked()
            return dict(job)

    def list_jobs(self) -> dict[str, Any]:
        with self.lock:
            for job in self.jobs.values():
                total_files = int(job.get("total_files") or 0)
                total_bytes = int(job.get("total_bytes") or 0)
                if total_files:
                    job["completed_files"] = min(int(job.get("completed_files") or 0), total_files)
                if total_bytes:
                    job["copied_bytes"] = min(int(job.get("copied_bytes") or 0), total_bytes)
            items = [dict(job) for job in self.jobs.values()]
            self._persist_jobs_locked()
        items.sort(key=lambda item: item.get("created_at", ""), reverse=True)
        return {"jobs": items[:20]}

    def _update(self, job_id: str, **values: Any) -> None:
        with self.lock:
            self.jobs[job_id].update(values)
            self._persist_jobs_locked(force=values.get("status") in {"completed", "completed_with_refresh_error"})

    def _add_copied_bytes(self, job_id: str, delta: int) -> None:
        with self.lock:
            job = self.jobs[job_id]
            job["copied_bytes"] = max(0, int(job.get("copied_bytes") or 0) + int(delta))
            self._persist_jobs_locked()

    def _copy_one(self, task: dict[str, Any], mode: str, progress: Any = None) -> None:
        source, target = task["source"], task["target"]
        source_root = self.computer if _under(self.computer, source) else self.nas
        target_root = self.computer if _under(self.computer, target) else self.nas
        if (
            not _under(source_root, source)
            or _contains_link(source_root, source)
            or not source.is_file()
            or is_link_or_reparse(source)
        ):
            raise RuntimeError("源文件不存在、不是普通文件，或为链接")
        if not _under(target_root, target) or _contains_link(target_root, target.parent):
            raise RuntimeError("目标路径不安全或包含链接")
        if target.exists() and not target.is_file():
            raise RuntimeError("目标已存在且不是普通文件，已跳过")
        if target.exists() and mode != "overwrite":
            raise RuntimeError("目标已存在；为避免覆盖，已跳过")
        if is_link_or_reparse(target):
            raise RuntimeError("目标为链接，已拒绝写入")
        target.parent.mkdir(parents=True, exist_ok=True)
        if not _under(target_root, target) or _contains_link(target_root, target.parent) or is_link_or_reparse(target.parent):
            raise RuntimeError("目标目录为链接，已拒绝写入")
        before = source.stat()
        temporary = target.with_name(f".{target.name}.workspace-os-{uuid.uuid4().hex}.partial")
        reported_bytes = 0
        try:
            with source.open("rb") as source_file, temporary.open("xb") as target_file:
                while True:
                    chunk = source_file.read(8 * 1024 * 1024)
                    if not chunk:
                        break
                    target_file.write(chunk)
                    reported_bytes += len(chunk)
                    if progress:
                        progress(len(chunk))
                target_file.flush()
                os.fsync(target_file.fileno())
            try:
                shutil.copystat(source, temporary, follow_symlinks=False)
            except OSError:
                # SMB shares frequently reject chmod/utime even though file data is writable.
                # Metadata preservation is best-effort; content size and source stability are
                # still verified below before the temporary file becomes visible.
                pass
            after = source.stat()
            if before.st_size != after.st_size or before.st_mtime_ns != after.st_mtime_ns:
                raise RuntimeError("复制期间源文件发生变化")
            if temporary.stat().st_size != before.st_size:
                raise RuntimeError("复制后大小不一致")
            if mode == "overwrite":
                os.replace(temporary, target)
            else:
                if target.exists():
                    raise RuntimeError("复制期间目标已出现同名文件；为避免覆盖，已停止")
                renamed_exclusively = False
                if sys.platform == "darwin":
                    try:
                        libc = ctypes.CDLL(None, use_errno=True)
                        renamex_np = libc.renamex_np
                        renamex_np.argtypes = [ctypes.c_char_p, ctypes.c_char_p, ctypes.c_uint]
                        renamex_np.restype = ctypes.c_int
                        result = renamex_np(
                            os.fsencode(temporary), os.fsencode(target), 0x00000004,
                        )  # RENAME_EXCL: atomic no-overwrite, supported by macOS SMB mounts.
                        if result == 0:
                            renamed_exclusively = True
                        else:
                            error_number = ctypes.get_errno()
                            if error_number == errno.EEXIST:
                                raise RuntimeError(
                                    "复制期间目标已出现同名文件；为避免覆盖，已停止"
                                )
                    except (AttributeError, OSError):
                        pass
                if renamed_exclusively:
                    return
                try:
                    os.link(temporary, target, follow_symlinks=False)
                    temporary.unlink()
                except FileExistsError as exc:
                    raise RuntimeError("复制期间目标已出现同名文件；为避免覆盖，已停止") from exc
                except OSError as exc:
                    unsupported = {errno.EPERM, errno.EACCES, errno.EXDEV}
                    if hasattr(errno, "ENOTSUP"):
                        unsupported.add(errno.ENOTSUP)
                    if hasattr(errno, "EOPNOTSUPP"):
                        unsupported.add(errno.EOPNOTSUPP)
                    if exc.errno not in unsupported:
                        raise
                    # Synology may reject RENAME_EXCL and hardlinks. O_EXCL
                    # never replaces an existing file. The destination remains
                    # incomplete until this final copy is flushed and checked.
                    descriptor = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
                    identity = os.fstat(descriptor)
                    try:
                        with os.fdopen(descriptor, "wb") as output, temporary.open("rb") as staged:
                            shutil.copyfileobj(staged, output, length=2 * 1024 * 1024)
                            output.flush()
                            os.fsync(output.fileno())
                            written = os.fstat(output.fileno())
                        if written.st_size != before.st_size:
                            raise RuntimeError("SMB 提交后大小不一致")
                        after_commit = source.stat()
                        if before.st_size != after_commit.st_size or before.st_mtime_ns != after_commit.st_mtime_ns:
                            raise RuntimeError("SMB 提交期间源文件发生变化")
                        try:
                            shutil.copystat(temporary, target, follow_symlinks=False)
                        except OSError:
                            pass
                    except Exception:
                        # Never remove a path another process replaced.
                        try:
                            current = target.lstat()
                            if (current.st_dev, current.st_ino) == (identity.st_dev, identity.st_ino):
                                target.unlink()
                        except OSError:
                            pass
                        raise
        except Exception:
            if progress and reported_bytes:
                progress(-reported_bytes)
            raise
        finally:
            try:
                temporary.unlink(missing_ok=True)
            except OSError:
                pass

    def _copy_one_with_robocopy(self, source: Path, target: Path, mode: str) -> None:
        before = source.stat()
        command = [
            "robocopy", str(source.parent), str(target.parent), source.name,
            "/COPY:DAT", "/DCOPY:DAT", "/R:1", "/W:1", "/XJ",
            "/NJH", "/NJS", "/NP",
        ]
        if mode == "overwrite":
            command.extend(["/IS", "/IT"])
        else:
            command.extend(["/XC", "/XN", "/XO"])
        creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        result = subprocess.run(
            command,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            creationflags=creationflags,
            timeout=1800,
        )
        if result.returncode >= 8:
            message = (result.stderr or result.stdout or "Windows 复制失败").strip()
            raise RuntimeError(message.splitlines()[-1] if message else "Windows 复制失败")
        if not target.is_file():
            raise RuntimeError("Windows 复制未生成目标文件")
        if mode != "overwrite":
            after = source.stat()
            if before.st_size != after.st_size or before.st_mtime_ns != after.st_mtime_ns:
                raise RuntimeError("复制期间源文件发生变化")
            if target.stat().st_size != before.st_size:
                raise RuntimeError("复制后大小不一致")

    def _robocopy_directory(self, source: Path, target: Path, mode: str) -> None:
        if not source.is_dir() or is_link_or_reparse(source):
            raise RuntimeError("源文件夹不存在、不是普通文件夹，或为链接")
        target.mkdir(parents=True, exist_ok=True)
        if is_link_or_reparse(target):
            raise RuntimeError("目标文件夹为链接，已拒绝写入")
        command = [
            "robocopy", str(source), str(target),
            "/E", "/COPY:DAT", "/DCOPY:DAT", "/R:1", "/W:1", "/XJ", "/MT:16",
            "/NJH", "/NJS", "/NP",
        ]
        if mode == "overwrite":
            command.extend(["/IS", "/IT"])
        else:
            command.extend(["/XC", "/XN", "/XO"])
        command.extend(["/XD", *sorted(SKIP_PARTS)])
        creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        result = subprocess.run(
            command,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            creationflags=creationflags,
            timeout=7200,
        )
        if result.returncode >= 8:
            message = (result.stderr or result.stdout or "Windows 文件夹复制失败").strip()
            raise RuntimeError(message.splitlines()[-1] if message else "Windows 文件夹复制失败")

    def _run(self, *args: Any) -> None:
        # Serialise transfers, including daily-log pull and target commits.
        with self.transfer_lock:
            self._run_serial(*args)

    def _run_serial(self, job_id: str, direction: str, selected: list[str], prefixes: list[str], mode: str) -> None:
        self._update(job_id, status="scanning", current="正在生成同步任务…")
        try:
            snapshot = None
            try:
                snapshot = json.loads(self.dashboard.with_suffix(".json").read_text(encoding="utf-8-sig"))
            except (OSError, UnicodeDecodeError, json.JSONDecodeError):
                snapshot = None
            source_root, target_root = (self.computer, self.nas) if direction == "to_nas" else (self.nas, self.computer)
            for root, label in ((source_root, "源路径"), (target_root, "目标路径")):
                ok, message = _path_available_quick(root)
                if not ok:
                    raise RuntimeError(f"{label}不可访问：{message}")
            ok, message = _target_writable_quick(target_root)
            if not ok:
                raise RuntimeError(f"目标路径不可写：{message}")
            selected_entries = self._source_entries_from_relatives(source_root, selected, mode, snapshot)
            if prefixes:
                selected_entries = {
                    relative: item for relative, item in selected_entries.items()
                    if not _covered_by_prefix(relative, prefixes)
                }
            prefix_entries = self._source_entries_from_prefixes(source_root, prefixes)
            entries = dict(selected_entries)
            entries.update(prefix_entries)
            tasks = []
            prefix_tasks = []
            missing = [item for item in selected if item not in entries]
            for prefix in prefixes:
                source_directory, target_directory = source_root / prefix, target_root / prefix
                prefix_items = [
                    {"relative": relative, "source": source_root / relative,
                     "target": target_root / relative, "size": item["size"]}
                    for relative, item in prefix_entries.items()
                    if relative == prefix or relative.startswith(prefix.rstrip("/") + "/")
                    if mode == "overwrite" or not (target_root / relative).is_file()
                ]
                if not _under(source_root, source_directory) or not _under(target_root, target_directory):
                    missing.append(prefix); continue
                if _contains_link(source_root, source_directory) or _contains_link(target_root, target_directory) or not source_directory.is_dir():
                    missing.append(prefix); continue
                prefix_tasks.append({
                    "relative": prefix, "source": source_directory, "target": target_directory,
                    "files": prefix_items,
                    "empty_unit": 1 if not prefix_items else 0,
                    "total_files": len(prefix_items), "total_bytes": sum(int(item["size"]) for item in prefix_items),
                })
            for relative, item in sorted(selected_entries.items()):
                source, target = source_root / relative, target_root / relative
                if not _under(source_root, source) or not _under(target_root, target):
                    missing.append(relative); continue
                if mode != "overwrite" and target.exists():
                    continue
                tasks.append({"relative": relative, "source": source, "target": target, "size": item["size"]})
            with self.lock:
                job = self.jobs[job_id]
                job["total_files"] = len(tasks) + sum(item["total_files"] + item["empty_unit"] for item in prefix_tasks)
                job["total_bytes"] = sum(item["size"] for item in tasks) + sum(item["total_bytes"] for item in prefix_tasks)
                job["errors"].extend({"relative": item, "message": "文件状态已变化，已跳过"} for item in missing)
            self._update(job_id, status="running", current="")
        except Exception as exc:
            self._update(job_id, status="completed_with_refresh_error", current="", refresh_error=str(exc))
            return
        transferred = []
        transferred_directories = []
        for task in prefix_tasks:
            self._update(job_id, current=f"正在复制文件夹：{task['relative']}")
            try:
                # Preserve the complete directory tree, including nested empty folders.
                for current, dirnames, _filenames in os.walk(task["source"]):
                    current_path = Path(current)
                    dirnames[:] = [
                        name for name in dirnames
                        if name.lower() not in SKIP_PARTS
                        and not is_link_or_reparse(current_path / name)
                    ]
                    relative_directory = current_path.relative_to(source_root)
                    destination_directory = target_root / relative_directory
                    if not _under(target_root, destination_directory) or _contains_link(target_root, destination_directory):
                        raise RuntimeError("目标文件夹路径不安全")
                    destination_directory.mkdir(parents=True, exist_ok=True)
                    transferred_directories.append(relative_directory.as_posix())
                if task["empty_unit"]:
                    with self.lock:
                        self.jobs[job_id]["completed_files"] += 1
                # File progress is updated only after each target is written and verified.
                for file_task in task["files"]:
                    self._update(job_id, current=file_task["relative"])
                    self._copy_one(
                        file_task, mode,
                        lambda delta, current_job=job_id: self._add_copied_bytes(current_job, delta),
                    )
                    transferred.append(file_task["relative"])
                    with self.lock:
                        self.jobs[job_id]["completed_files"] += 1
            except Exception as exc:
                with self.lock:
                    self.jobs[job_id]["errors"].append({"relative": task["relative"], "message": str(exc)})
        for task in tasks:
            self._update(job_id, current=task["relative"])
            try:
                self._copy_one(
                    task, mode,
                    lambda delta, current_job=job_id: self._add_copied_bytes(current_job, delta),
                )
                transferred.append(task["relative"])
                with self.lock:
                    self.jobs[job_id]["completed_files"] += 1
            except Exception as exc:  # Preserve successfully copied prior files; never roll them back.
                with self.lock:
                    self.jobs[job_id]["errors"].append({"relative": task["relative"], "message": str(exc)})
        try:
            self._update(job_id, current="正在刷新差异列表…")
            # A local test workspace can be re-scanned immediately. For a
            # relayed UNC NAS, avoid blocking the completed job on a full SMB
            # walk; the user can explicitly press “刷新目录” for live NAS data.
            live_after_copy = not str(self.nas).startswith(("/Volumes/", "\\\\"))
            self._snapshot(live_nas=live_after_copy, transferred=transferred + transferred_directories)
            try:
                log_path = self._append_obsidian_sync_log(self.jobs[job_id], transferred)
                local_log_path = self._pull_obsidian_log_to_local(log_path)
                self._update(job_id, status="completed", current="", log_path=log_path,
                             local_log_path=local_log_path, local_log_preserved=self.last_preserved_log,
                             refreshed_at=datetime.now(timezone.utc).isoformat())
            except OSError as log_exc:
                # File transfer remains successful; expose the log failure so it is actionable.
                self._update(job_id, status="completed", current="同步完成，但 NAS 日志同步到本地失败",
                             log_error=str(log_exc), refreshed_at=datetime.now(timezone.utc).isoformat())
        except Exception as exc:
            self._update(
                job_id, status="completed_with_refresh_error", current="",
                refresh_error=str(exc), refreshed_at="",
            )


def serve(computer: str, nas: str, dashboard: str, port: int, idle_timeout: float = 30.0, ready_file: str | None = None) -> None:
    jobs = SyncJobs(Path(computer), Path(nas), Path(dashboard))
    activity = {"last": time.monotonic()}

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, _format: str, *_args: Any) -> None:
            return

        def send_json(self, status: int, body: dict[str, Any]) -> None:
            data = json.dumps(body, ensure_ascii=False).encode("utf-8")
            self.send_response(status); self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Length", str(len(data))); self.end_headers(); self.wfile.write(data)

        def local_browser_request(self) -> bool:
            expected = f"127.0.0.1:{self.server.server_port}"
            if self.headers.get("Host") != expected:
                return False
            origin = self.headers.get("Origin")
            if origin and origin != f"http://{expected}":
                return False
            return self.headers.get("Sec-Fetch-Site") not in {"cross-site"}

        def do_GET(self) -> None:
            if not self.local_browser_request():
                self.send_json(HTTPStatus.FORBIDDEN, {"error": "仅允许本机同源请求"})
                return
            activity["last"] = time.monotonic()
            path = urlparse(self.path).path
            if path == "/api/health":
                self.send_json(HTTPStatus.OK, {
                    "ok": True,
                    "api_version": "2.1",
                    "computer": str(jobs.computer),
                    "nas": str(jobs.nas),
                    "dashboard": str(jobs.dashboard),
                })
                return
            if path == "/api/sync/jobs":
                self.send_json(HTTPStatus.OK, jobs.list_jobs())
                return
            if path == "/api/open-folder":
                try:
                    query = parse_qs(urlparse(self.path).query)
                    side = (query.get("side") or [""])[0]
                    relative = (query.get("relative") or [""])[0]
                    self.send_json(HTTPStatus.OK, jobs.open_folder(side, relative))
                except (ValueError, FileNotFoundError, OSError) as exc:
                    self.send_json(HTTPStatus.BAD_REQUEST, {"error": str(exc)})
                return
            if path == "/api/open-folder-path":
                try:
                    query = parse_qs(urlparse(self.path).query)
                    raw_path = (query.get("path") or [""])[0]
                    self.send_json(HTTPStatus.OK, jobs.open_folder_path(raw_path))
                except (ValueError, FileNotFoundError, OSError) as exc:
                    self.send_json(HTTPStatus.BAD_REQUEST, {"error": str(exc)})
                return
            if path in {"/", "/dashboard"}:
                try:
                    content = jobs.dashboard.read_bytes()
                except OSError as exc:
                    self.send_json(HTTPStatus.NOT_FOUND, {"error": str(exc)}); return
                self.send_response(HTTPStatus.OK); self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Cache-Control", "no-store")
                self.send_header("Content-Length", str(len(content))); self.end_headers(); self.wfile.write(content); return
            if path.startswith("/api/sync/jobs/"):
                try:
                    self.send_json(HTTPStatus.OK, jobs.status(path.rsplit("/", 1)[-1]))
                except KeyError:
                    self.send_json(HTTPStatus.NOT_FOUND, {"error": "任务不存在"})
                return
            self.send_json(HTTPStatus.NOT_FOUND, {"error": "not found"})

        def do_POST(self) -> None:
            if not self.local_browser_request():
                self.send_json(HTTPStatus.FORBIDDEN, {"error": "仅允许本机同源请求"})
                return
            activity["last"] = time.monotonic()
            path = urlparse(self.path).path
            if path == "/api/refresh":
                try:
                    query = urlparse(self.path).query
                    live_nas = "live=1" in query or "live=true" in query.lower()
                    self.send_json(HTTPStatus.OK, jobs.refresh_snapshot(live_nas=live_nas))
                except Exception as exc:
                    self.send_json(HTTPStatus.INTERNAL_SERVER_ERROR, {"error": str(exc)})
                return
            if path != "/api/sync/jobs":
                self.send_json(HTTPStatus.NOT_FOUND, {"error": "not found"}); return
            try:
                length = int(self.headers.get("Content-Length", "0"))
                if length <= 0 or length > 1_000_000:
                    raise ValueError("请求过大")
                body = json.loads(self.rfile.read(length).decode("utf-8"))
                if not isinstance(body, dict):
                    raise ValueError("请求必须为对象")
                result = jobs.start(
                    body.get("direction"),
                    body.get("relatives") or [],
                    body.get("prefixes") or [],
                    body.get("mode") or "safe",
                )
                self.send_json(HTTPStatus.ACCEPTED, result)
            except (ValueError, TypeError, json.JSONDecodeError) as exc:
                self.send_json(HTTPStatus.BAD_REQUEST, {"error": str(exc)})
            except Exception as exc:
                self.send_json(HTTPStatus.INTERNAL_SERVER_ERROR, {"error": str(exc)})

    server = ThreadingHTTPServer(("127.0.0.1", port), Handler)

    if ready_file:
        Path(ready_file).write_text(json.dumps({"port": server.server_port}), encoding="utf-8")

    def reap_when_idle() -> None:
        while True:
            time.sleep(5)
            if idle_timeout <= 0 or time.monotonic() - activity["last"] < idle_timeout:
                continue
            running = any(job.get("status") in {"queued", "scanning", "running"} for job in jobs.list_jobs().get("jobs", []))
            if running:
                activity["last"] = time.monotonic()
                continue
            server.shutdown()
            return

    threading.Thread(target=reap_when_idle, name="workspace-os-dashboard-idle-reaper", daemon=True).start()
    server.serve_forever()


def main() -> int:
    parser = argparse.ArgumentParser(description="Workspace OS local dashboard sync service")
    parser.add_argument("--computer", required=True); parser.add_argument("--nas", required=True)
    parser.add_argument("--dashboard", required=True); parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--idle-timeout", type=float, default=30.0)
    args = parser.parse_args()
    serve(args.computer, args.nas, args.dashboard, args.port, args.idle_timeout)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
