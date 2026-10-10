"""构建可迁移的本地 JSON 文件索引。"""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from duplicate_finder import sha256_file
from path_safety import iter_files_no_links
from version_detector import parse_version

SKIP_NAMES = {".git", "__pycache__", ".DS_Store", "Thumbs.db"}


def _project_for(path: Path, root: Path) -> str | None:
    parts = path.relative_to(root).parts
    if "Active" in parts:
        idx = parts.index("Active")
        return parts[idx + 1] if len(parts) > idx + 1 else None
    return None


def build_index(root: str | Path, include_hash: bool = False) -> dict[str, Any]:
    base = Path(root).resolve()
    records = []
    for path in sorted(iter_files_no_links(base)):
        if not path.is_file() or any(part in SKIP_NAMES for part in path.parts):
            continue
        try:
            stat = path.stat()
        except OSError:
            continue
        parsed = parse_version(path)
        relative = path.relative_to(base).as_posix()
        category = relative.split("/", 1)[0]
        records.append({
            "path": relative, "name": path.name, "extension": path.suffix.lower(), "size": stat.st_size,
            "created_time": datetime.fromtimestamp(stat.st_ctime, timezone.utc).isoformat(),
            "modified_time": datetime.fromtimestamp(stat.st_mtime, timezone.utc).isoformat(),
            "project": _project_for(path, base), "category": category,
            "version": parsed["version_text"], "status": parsed["status"], "tags": [],
            "sha256": sha256_file(path) if include_hash else None, "summary": "", "device": "",
            "archive_state": "archived" if "99_Archive" in path.parts else "active",
        })
    return {"schema_version": "1.0", "generated_at": datetime.now(timezone.utc).isoformat(),
            "root": str(base), "file_count": len(records), "files": records}


def save_index(index: dict[str, Any], output: str | Path) -> Path:
    target = Path(output)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(index, ensure_ascii=False, indent=2), encoding="utf-8")
    return target


def search_index(index: dict[str, Any], query: str = "", **filters: Any) -> list[dict[str, Any]]:
    query_lower = query.lower()
    date_from = filters.pop("date_from", None)
    date_to = filters.pop("date_to", None)
    released_only = filters.pop("released_only", False)
    result = []
    for record in index.get("files", []):
        haystack = " ".join([record.get("name", ""), record.get("path", ""), record.get("summary", ""),
                             " ".join(record.get("tags", []))]).lower()
        if query_lower and query_lower not in haystack:
            continue
        modified = record.get("modified_time", "")[:10]
        if date_from and modified < date_from:
            continue
        if date_to and modified > date_to:
            continue
        if released_only and record.get("status") not in {"RELEASE", "APPROVED"} and "release" not in record.get("path", "").lower():
            continue
        if any(value is not None and str(record.get(key, "")).lower() != str(value).lower()
               for key, value in filters.items()):
            continue
        result.append(record)
    return result
