"""Detect suspicious workspace change bursts using privacy-preserving metadata."""
from __future__ import annotations

import json
import math
import os
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from path_safety import is_link_or_reparse

SKIP_DIRECTORY_NAMES = {
    ".git", ".pytest_cache", ".venv", ".vs", "__pycache__", "node_modules",
}
SKIP_PREFIXES = {
    "07_admin/workspaceos",
    "08_indexes",
}
SUSPICIOUS_EXTENSIONS = {
    ".crypt", ".crypted", ".encrypted", ".locked", ".lockbit", ".ryk", ".ryuk", ".wncry",
}
RANSOM_NOTE_TOKENS = {
    "decrypt_instructions", "how_to_decrypt", "how_to_restore", "readme_to_decrypt",
    "restore_files", "restore_my_files",
}
SEVERITY_RANK = {"INFO": 0, "WARNING": 1, "ERROR": 2, "CRITICAL": 3}


def _read_json(path: Path) -> dict[str, Any] | None:
    try:
        value = json.loads(path.read_text(encoding="utf-8-sig"))
        return value if isinstance(value, dict) else None
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return None


def _atomic_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(temporary, path)


def _excluded(relative: Path) -> bool:
    lowered_parts = tuple(part.lower() for part in relative.parts)
    if any(part in SKIP_DIRECTORY_NAMES for part in lowered_parts):
        return True
    normalized = relative.as_posix().lower()
    return any(normalized == prefix or normalized.startswith(prefix + "/") for prefix in SKIP_PREFIXES)


def inventory_workspace(workspace: str | Path) -> dict[str, dict[str, Any]]:
    root = Path(workspace).expanduser().resolve()
    inventory: dict[str, dict[str, Any]] = {}
    for current, dirnames, filenames in os.walk(root):
        current_path = Path(current)
        try:
            current_relative = current_path.relative_to(root)
        except ValueError:
            continue
        dirnames[:] = [
            name for name in dirnames
            if not _excluded(current_relative / name)
            and not is_link_or_reparse(current_path / name)
        ]
        for name in filenames:
            path = current_path / name
            try:
                relative_path = path.relative_to(root)
                if _excluded(relative_path) or is_link_or_reparse(path):
                    continue
                stat = path.stat()
            except (OSError, ValueError):
                continue
            relative = relative_path.as_posix()
            inventory[relative] = {
                "size": stat.st_size,
                "modified_ns": stat.st_mtime_ns,
                "extension": path.suffix.lower(),
            }
    return inventory


def _baseline_payload(workspace: Path, inventory: dict[str, dict[str, Any]]) -> dict[str, Any]:
    return {
        "schema_version": "1.0",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "workspace": str(workspace),
        "privacy_mode": "metadata-only",
        "file_count": len(inventory),
        "files": inventory,
    }


def analyze_change_guard(
    workspace: str | Path,
    baseline: dict[str, Any] | None,
    current: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    root = Path(workspace).expanduser().resolve()
    now = datetime.now(timezone.utc).isoformat()
    if not baseline or not isinstance(baseline.get("files"), dict):
        return {
            "schema_version": "1.0",
            "generated_at": now,
            "workspace": str(root),
            "status": "learning",
            "privacy_mode": "metadata-only",
            "summary": {
                "previous_files": 0,
                "current_files": len(current),
                "added": len(current),
                "deleted": 0,
                "modified": 0,
                "encrypted_renames": 0,
                "suspicious_extensions": 0,
                "ransom_notes": 0,
            },
            "findings": [],
            "samples": {},
        }

    previous = baseline["files"]
    previous_paths, current_paths = set(previous), set(current)
    added = sorted(current_paths - previous_paths)
    deleted = sorted(previous_paths - current_paths)
    modified = sorted(
        path for path in previous_paths & current_paths
        if (
            previous[path].get("size") != current[path].get("size")
            or previous[path].get("modified_ns") != current[path].get("modified_ns")
        )
    )
    encrypted_renames = sorted(
        new_path for new_path in added
        if Path(new_path).suffix.lower() in SUSPICIOUS_EXTENSIONS
        and new_path[: -len(Path(new_path).suffix)] in previous_paths
        and new_path[: -len(Path(new_path).suffix)] in deleted
    )
    suspicious = sorted(path for path in added if Path(path).suffix.lower() in SUSPICIOUS_EXTENSIONS)
    ransom_notes = sorted(
        path for path in added
        if any(token in Path(path).stem.lower() for token in RANSOM_NOTE_TOKENS)
    )
    findings: list[dict[str, Any]] = []

    def add_finding(severity: str, code: str, message: str, count: int) -> None:
        findings.append({"severity": severity, "code": code, "message": message, "count": count})

    previous_count = max(1, len(previous))
    delete_threshold = max(25, math.ceil(previous_count * 0.10))
    modify_threshold = max(100, math.ceil(previous_count * 0.35))
    if len(deleted) >= delete_threshold:
        add_finding("ERROR", "MASS_DELETION", "检测到异常规模的文件删除", len(deleted))
    if len(modified) >= modify_threshold:
        add_finding("ERROR", "MASS_MODIFICATION", "检测到异常规模的文件修改", len(modified))
    if len(encrypted_renames) >= 3:
        add_finding("CRITICAL", "ENCRYPTED_RENAME_BURST", "多个原文件被替换为疑似加密扩展名", len(encrypted_renames))
    elif suspicious:
        add_finding("WARNING", "SUSPICIOUS_EXTENSION", "发现新增的疑似加密扩展名文件", len(suspicious))
    if ransom_notes:
        add_finding("CRITICAL", "RANSOM_NOTE_DETECTED", "发现疑似勒索说明文件名", len(ransom_notes))

    highest = max((SEVERITY_RANK[item["severity"]] for item in findings), default=0)
    status = "critical" if highest == 3 else "error" if highest == 2 else "warning" if highest == 1 else "healthy"
    return {
        "schema_version": "1.0",
        "generated_at": now,
        "workspace": str(root),
        "status": status,
        "privacy_mode": "metadata-only",
        "thresholds": {
            "mass_deletion_files": delete_threshold,
            "mass_modification_files": modify_threshold,
            "encrypted_rename_burst": 3,
        },
        "summary": {
            "previous_files": len(previous),
            "current_files": len(current),
            "added": len(added),
            "deleted": len(deleted),
            "modified": len(modified),
            "encrypted_renames": len(encrypted_renames),
            "suspicious_extensions": len(suspicious),
            "ransom_notes": len(ransom_notes),
        },
        "findings": findings,
        "samples": {
            "added": added[:20],
            "deleted": deleted[:20],
            "modified": modified[:20],
            "encrypted_renames": encrypted_renames[:20],
            "suspicious_extensions": suspicious[:20],
            "ransom_notes": ransom_notes[:20],
        },
    }


def run_change_guard(
    workspace: str | Path,
    baseline_path: str | Path,
    output: str | Path,
    *,
    accept: bool = False,
) -> tuple[dict[str, Any], Path, Path]:
    root = Path(workspace).expanduser().resolve()
    baseline_file = Path(baseline_path)
    output_file = Path(output)
    previous = _read_json(baseline_file)
    current = inventory_workspace(root)
    report = analyze_change_guard(root, previous, current)
    should_update = report["status"] in {"learning", "healthy"} or accept
    if should_update:
        _atomic_json(baseline_file, _baseline_payload(root, current))
    report["baseline_updated"] = should_update
    report["baseline_update_reason"] = (
        "explicitly-accepted" if accept and report["status"] not in {"learning", "healthy"}
        else "trusted-current-state" if should_update
        else "frozen-due-to-findings"
    )
    _atomic_json(output_file, report)
    return report, baseline_file, output_file
