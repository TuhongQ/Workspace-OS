"""Shared safety checks for ZIP members and manifest-relative paths."""
from __future__ import annotations

import re
import stat
from collections import Counter
from pathlib import PurePosixPath
from typing import Any
from zipfile import ZipInfo

DRIVE_PREFIX = re.compile(r"^[A-Za-z]:")


def safe_relative_path(value: object) -> bool:
    if not isinstance(value, str) or not value or "\x00" in value or "\\" in value:
        return False
    if value.startswith(("/", "//")) or DRIVE_PREFIX.match(value):
        return False
    path = PurePosixPath(value)
    return (
        not path.is_absolute()
        and ".." not in path.parts
        and "." not in path.parts
        and all(part not in {"", ".", ".."} for part in path.parts)
    )


def inspect_zip_members(infos: list[ZipInfo]) -> list[dict[str, Any]]:
    issues: list[dict[str, Any]] = []
    names = [info.filename for info in infos]
    for name, count in sorted(Counter(names).items()):
        if count > 1:
            issues.append({
                "code": "DUPLICATE_ARCHIVE_MEMBER",
                "path": name,
                "count": count,
            })
    for info in infos:
        name = info.filename
        normalized = name[:-1] if name.endswith("/") else name
        if not safe_relative_path(normalized):
            issues.append({"code": "UNSAFE_ARCHIVE_PATH", "path": name})
        unix_mode = (info.external_attr >> 16) & 0xFFFF
        if stat.S_IFMT(unix_mode) == stat.S_IFLNK:
            issues.append({"code": "SYMLINK_ARCHIVE_MEMBER", "path": name})
        if info.flag_bits & 0x1:
            issues.append({"code": "ENCRYPTED_ARCHIVE_MEMBER", "path": name})
    return issues
