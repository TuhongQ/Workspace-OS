"""Cross-platform link and Windows reparse-point safety helpers."""
from __future__ import annotations

from pathlib import Path
import os
from collections.abc import Iterator

FILE_ATTRIBUTE_REPARSE_POINT = 0x400


def is_reparse_point(path: str | Path) -> bool:
    candidate = Path(path)
    try:
        attributes = int(getattr(candidate.lstat(), "st_file_attributes", 0))
    except OSError:
        return False
    return bool(attributes & FILE_ATTRIBUTE_REPARSE_POINT)


def is_link_or_reparse(path: str | Path) -> bool:
    candidate = Path(path)
    try:
        return candidate.is_symlink() or is_reparse_point(candidate)
    except OSError:
        return True


def link_escapes_root(path: str | Path, root: str | Path) -> bool:
    candidate = Path(path)
    base = Path(root).resolve()
    try:
        candidate.resolve(strict=False).relative_to(base)
        return False
    except (OSError, ValueError):
        return True


def iter_files_no_links(root: str | Path) -> Iterator[Path]:
    base = Path(root)
    for current, dirnames, filenames in os.walk(base, followlinks=False):
        current_path = Path(current)
        dirnames[:] = [
            name
            for name in dirnames
            if not is_link_or_reparse(current_path / name)
        ]
        for name in sorted(filenames):
            path = current_path / name
            if not is_link_or_reparse(path):
                yield path


def iter_paths_no_links(root: str | Path) -> Iterator[Path]:
    base = Path(root)
    for current, dirnames, filenames in os.walk(base, followlinks=False):
        current_path = Path(current)
        kept_directories = []
        for name in sorted(dirnames):
            path = current_path / name
            if is_link_or_reparse(path):
                continue
            kept_directories.append(name)
            yield path
        dirnames[:] = kept_directories
        for name in sorted(filenames):
            path = current_path / name
            if not is_link_or_reparse(path):
                yield path


def find_link_entries(root: str | Path) -> list[Path]:
    """Return links/reparse points without traversing through any of them."""
    base = Path(root)
    if is_link_or_reparse(base):
        return [base]
    if not base.is_dir():
        return []
    found: list[Path] = []
    for current, dirnames, filenames in os.walk(base, followlinks=False):
        current_path = Path(current)
        kept_directories = []
        for name in sorted(dirnames):
            path = current_path / name
            if is_link_or_reparse(path):
                found.append(path)
            else:
                kept_directories.append(name)
        dirnames[:] = kept_directories
        for name in sorted(filenames):
            path = current_path / name
            if is_link_or_reparse(path):
                found.append(path)
    return sorted(found, key=lambda path: str(path).casefold())
