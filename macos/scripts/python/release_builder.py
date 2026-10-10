"""安全构建发布目录、清单与校验和。"""
from __future__ import annotations

import json
import os
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from duplicate_finder import sha256_file
from path_safety import find_link_entries, is_link_or_reparse, iter_files_no_links, iter_paths_no_links


def _validate_release_sources(source: Path, operations: list[str]) -> None:
    for name in operations:
        item = source / name
        unsafe = find_link_entries(item)
        if unsafe:
            relative = unsafe[0].relative_to(source).as_posix()
            raise ValueError(f"UNSAFE_RELEASE_SOURCE_LINK: {relative}")


def manifest_for(root: str | Path, version: str = "unknown") -> dict[str, Any]:
    base = Path(root).resolve()
    unsafe = find_link_entries(base)
    if unsafe:
        relative = unsafe[0].relative_to(base).as_posix()
        raise ValueError(f"UNSAFE_RELEASE_OUTPUT_LINK: {relative}")
    files = []
    for path in sorted(iter_files_no_links(base)):
        if path.is_file() and path.name not in {"SHA256SUMS.txt", "release-manifest.json"}:
            stat = path.stat()
            files.append({"path": path.relative_to(base).as_posix(), "size": stat.st_size,
                          "sha256": sha256_file(path), "modified_time": datetime.fromtimestamp(stat.st_mtime, timezone.utc).isoformat()})
    return {"schema_version": "1.0", "release_version": version,
            "generated_at": datetime.now(timezone.utc).isoformat(), "files": files}


def write_manifest(root: str | Path, version: str = "unknown") -> tuple[Path, Path]:
    base = Path(root)
    manifest = manifest_for(base, version)
    manifest_path = base / "release-manifest.json"
    sums_path = base / "SHA256SUMS.txt"
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    sums_path.write_text("".join(f"{item['sha256']}  {item['path']}\n" for item in manifest["files"]), encoding="utf-8")
    return manifest_path, sums_path


def build_release(source: str | Path, destination: str | Path | None = None,
                  version: str = "unknown", apply: bool = False) -> dict[str, Any]:
    src = Path(source).resolve()
    if not src.is_dir():
        raise FileNotFoundError(f"发布源目录不存在: {src}")
    dst = Path(destination).resolve() if destination else src / "release" / version
    operations = [
        str(p.relative_to(src))
        for p in src.iterdir()
        if p.name not in {"release", "archive", "builds", "proxies", "logs"}
    ]
    _validate_release_sources(src, operations)
    plan = {"source": str(src), "destination": str(dst), "version": version, "apply": apply,
            "operations": operations}
    if not apply:
        return plan
    if dst.exists() and any(dst.iterdir()):
        raise FileExistsError(f"目标发布目录非空，拒绝覆盖: {dst}")
    dst.mkdir(parents=True, exist_ok=True)
    try:
        for name in plan["operations"]:
            item = src / name
            target = dst / name
            if is_link_or_reparse(item):
                raise ValueError(f"UNSAFE_RELEASE_SOURCE_LINK: {name}")
            if item.is_dir():
                target.mkdir(parents=True, exist_ok=False)
                for path in iter_paths_no_links(item):
                    relative = path.relative_to(item)
                    copied = target / relative
                    if path.is_dir():
                        copied.mkdir(parents=True, exist_ok=True)
                    elif path.is_file():
                        copied.parent.mkdir(parents=True, exist_ok=True)
                        shutil.copy2(path, copied)
            else:
                shutil.copy2(item, target)
        _validate_release_sources(src, operations)
        unsafe_destination = find_link_entries(dst)
        if unsafe_destination:
            relative = unsafe_destination[0].relative_to(dst).as_posix()
            raise ValueError(f"UNSAFE_RELEASE_OUTPUT_LINK: {relative}")
        for required in ("README.md", "CHANGELOG.md"):
            if not (dst / required).exists():
                (dst / required).write_text(f"# {required[:-3]}\n\n发布版本：{version}\n", encoding="utf-8")
        write_manifest(dst, version)
    except Exception:
        # 不删除用户源文件；只清理由本次创建且尚未交付的目标。
        shutil.rmtree(dst, ignore_errors=True)
        raise
    return plan
