"""Copy only release-owned source, never caches, nested apps or user workspaces."""
import shutil
import sys
from pathlib import Path

source, destination = (Path(p).resolve() for p in sys.argv[1:])
if destination == source or source in destination.parents:
    raise SystemExit("Release destination must be outside source")
destination.mkdir(parents=True, exist_ok=False)
allowed = {"assets", "config", "docs", "examples", "migration", "nas", "obsidian",
           "scripts", "search", "shortcuts", "templates", "tests", "workspace-sample",
           "README.md", "CHANGELOG.md", "LICENSE", "VERSION"}
excluded = {".DS_Store", "__pycache__", ".git", ".venv", "node_modules", ".pytest_cache"}
def ignore(directory, names):
    return [name for name in names if name in excluded or name.endswith((".pyc", ".app"))
            or (Path(directory) / name).is_symlink()]
for name in sorted(allowed):
    path = source / name
    if not path.exists() or path.is_symlink():
        continue
    if path.is_dir():
        shutil.copytree(path, destination / name, ignore=ignore)
    else:
        shutil.copy2(path, destination / name)
