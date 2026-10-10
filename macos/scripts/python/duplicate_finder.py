"""先按大小、再按 SHA-256 查找二进制完全相同的文件。"""
from __future__ import annotations

import csv
import hashlib
import json
from collections import defaultdict
from pathlib import Path
from typing import Any

from path_safety import iter_files_no_links

CHUNK_SIZE = 4 * 1024 * 1024
SKIP_DIRECTORY_NAMES = {".vs", "__pycache__", ".pytest_cache", "node_modules", ".venv"}


def sha256_file(path: str | Path, chunk_size: int = CHUNK_SIZE) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for chunk in iter(lambda: stream.read(chunk_size), b""):
            digest.update(chunk)
    return digest.hexdigest()


def find_duplicates(root: str | Path) -> list[dict[str, Any]]:
    by_size: dict[int, list[Path]] = defaultdict(list)
    for path in iter_files_no_links(root):
        if path.is_file() and not ({part.lower() for part in path.parts} & SKIP_DIRECTORY_NAMES):
            try:
                by_size[path.stat().st_size].append(path)
            except OSError:
                pass
    by_hash: dict[tuple[int, str], list[Path]] = defaultdict(list)
    for size, paths in by_size.items():
        if len(paths) > 1:
            for path in paths:
                try:
                    by_hash[(size, sha256_file(path))].append(path)
                except OSError:
                    pass
    groups = []
    for (size, digest), paths in by_hash.items():
        if len(paths) > 1:
            ordered = sorted(paths, key=lambda p: ("archive" in str(p).lower(), len(str(p)), str(p)))
            groups.append({"hash": digest, "size": size, "file_count": len(paths),
                           "paths": [str(p) for p in ordered], "recommended_primary": str(ordered[0]),
                           "reason": "文件大小和 SHA-256 均相同；仅报告，不自动删除。"})
    return sorted(groups, key=lambda x: (-x["size"], x["hash"]))


def write_reports(groups: list[dict[str, Any]], json_path: str | Path, csv_path: str | Path) -> None:
    Path(json_path).write_text(json.dumps(groups, ensure_ascii=False, indent=2), encoding="utf-8")
    with Path(csv_path).open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=["hash", "size", "file_count", "paths", "recommended_primary", "reason"])
        writer.writeheader()
        for group in groups:
            writer.writerow({**group, "paths": " | ".join(group["paths"])})


class SimilarVideoDetector:
    """近似视频检测扩展接口；默认不启用，也不把相似文件当作重复。"""
    def compare(self, first: Path, second: Path) -> float:
        raise NotImplementedError
