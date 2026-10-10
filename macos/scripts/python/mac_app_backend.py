"""Local AppKit host backend. Never mounts, syncs, or copies user files at startup."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import threading
import time
from pathlib import Path

from dashboard_sync_server import SyncJobs, serve


def validate_roots(computer: str, nas: str) -> tuple[Path, Path]:
    local, remote = Path(computer).expanduser(), Path(nas).expanduser()
    if not local.is_absolute() or not remote.is_absolute():
        raise ValueError("工作区必须使用绝对路径")
    local, remote = local.resolve(), remote.resolve()
    if local == remote or local in remote.parents or remote in local.parents:
        raise ValueError("本地与 NAS 不能相同或互相包含")
    if not local.is_dir():
        raise ValueError("本地工作区不存在；请在设置中选择现有工作区")
    return local, remote


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--computer", required=True)
    parser.add_argument("--nas", required=True)
    parser.add_argument("--ready-file", required=True)
    parser.add_argument("--parent-pid", type=int)
    args = parser.parse_args()
    computer, nas = validate_roots(args.computer, args.nas)
    key = hashlib.sha256(f"{computer}\0{nas}".encode()).hexdigest()[:16]
    runtime = Path.home() / "Library/Caches/WorkspaceOS" / key
    runtime.mkdir(parents=True, exist_ok=True)
    dashboard = runtime / "file-locations.html"
    previous = dashboard.with_suffix(".json")
    if not previous.exists():
        candidates = [
            Path.home() / "Library/Caches/WorkspaceOS/dashboard/file-locations.json",
            computer / "08_Indexes/file-locations.json",
        ]
        for candidate in candidates:
            try:
                payload = json.loads(candidate.read_text(encoding="utf-8-sig"))
                if payload.get("nas_root") == str(nas):
                    previous.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
                    break
            except (OSError, ValueError):
                continue
    # Start from cached NAS inventory for a responsive launch. Live SMB traversal
    # is always an explicit Refresh action, never an automatic transfer.
    SyncJobs(computer, nas, dashboard)._snapshot(live_nas=False)
    parent = args.parent_pid or os.getppid()
    def watch_parent() -> None:
        while True:
            time.sleep(5)
            try:
                os.kill(parent, 0)
            except ProcessLookupError:
                # Preserve interrupted status on disk; no user data is removed.
                os._exit(0)
            except PermissionError:
                pass
    threading.Thread(target=watch_parent, daemon=True).start()
    serve(str(computer), str(nas), str(dashboard), 0, idle_timeout=0, ready_file=args.ready_file)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
