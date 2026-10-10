#!/usr/bin/env python3
"""Backend dispatcher embedded beside the standalone macOS GUI executable."""
from __future__ import annotations

import os
import runpy
import sys
from pathlib import Path


def main() -> int:
    if len(sys.argv) < 2 or sys.argv[1] not in {"cli", "server", "desktop"}:
        print("usage: WorkspaceOSHelper {cli|server|desktop} [arguments...]", file=sys.stderr)
        return 2
    root_value = os.environ.get("WORKSPACE_OS_ROOT", "").strip()
    if not root_value:
        print("WORKSPACE_OS_ROOT is not configured", file=sys.stderr)
        return 2
    root = Path(root_value).expanduser().resolve()
    python_root = root / "scripts" / "python"
    script_name = {"cli": "workspace_cli.py", "server": "dashboard_sync_server.py",
                   "desktop": "mac_app_backend.py"}[sys.argv[1]]
    script = python_root / script_name
    if not script.is_file():
        print(f"Workspace OS backend is missing: {script}", file=sys.stderr)
        return 2
    sys.path.insert(0, str(python_root))
    sys.argv = [str(script), *sys.argv[2:]]
    runpy.run_path(str(script), run_name="__main__")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
