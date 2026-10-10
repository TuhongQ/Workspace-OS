"""Safe, isolated canary restore drills for verified Workspace snapshots."""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from backup import MANIFEST_NAME
from path_safety import is_link_or_reparse

SCHEMA_VERSION = "1.0"
ELIGIBLE_TOP_LEVELS = {
    "00_Inbox",
    "01_Projects",
    "02_Knowledge",
    "03_Media",
    "04_AI",
    "05_Shared",
    "06_Release",
    "09_Templates",
}
EXCLUDED_PARTS = {
    ".git",
    ".vs",
    "__pycache__",
    "node_modules",
    ".venv",
    "private",
    "accounts",
    "certificates",
    "secrets",
}


def _read_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(value, dict):
        raise ValueError(f"JSON object required: {path}")
    return value


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _safe_member(root: Path, relative: str) -> Path:
    if not relative or Path(relative).is_absolute():
        raise ValueError(f"Unsafe snapshot member: {relative}")
    target = (root / Path(relative)).resolve(strict=False)
    try:
        target.relative_to(root)
    except ValueError as exc:
        raise ValueError(f"Snapshot member escapes its root: {relative}") from exc
    return target


def _atomic_json(path: Path, value: dict[str, Any]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
            json.dump(value, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    except Exception:
        try:
            os.unlink(temporary)
        except OSError:
            pass
        raise
    return path


def _is_eligible(item: dict[str, Any], max_file_bytes: int) -> bool:
    relative = item.get("path")
    size = item.get("size")
    if not isinstance(relative, str) or not isinstance(size, int):
        return False
    if size < 0 or size > max_file_bytes:
        return False
    parts = Path(relative).parts
    if not parts:
        return False
    lowered = {part.casefold() for part in parts}
    if lowered & EXCLUDED_PARTS:
        return False
    return relative == ".workspace-os.json" or parts[0] in ELIGIBLE_TOP_LEVELS


def _select_canaries(
    files: list[dict[str, Any]],
    *,
    seed: str,
    sample_count: int,
    max_file_bytes: int,
    max_total_bytes: int,
) -> list[dict[str, Any]]:
    candidates = [item for item in files if _is_eligible(item, max_file_bytes)]
    candidates.sort(
        key=lambda item: hashlib.sha256(f"{seed}\0{item['path']}".encode("utf-8")).hexdigest()
    )
    selected: list[dict[str, Any]] = []
    selected_paths: set[str] = set()
    total = 0

    marker = next((item for item in candidates if item["path"] == ".workspace-os.json"), None)
    if marker and marker["size"] <= max_total_bytes:
        selected.append(marker)
        selected_paths.add(marker["path"])
        total += marker["size"]

    # First choose one file from each available top-level category. This proves
    # path creation across the workspace instead of clustering every sample in
    # one directory.
    for top_level in sorted(ELIGIBLE_TOP_LEVELS):
        item = next(
            (
                candidate
                for candidate in candidates
                if Path(candidate["path"]).parts[0] == top_level
                and candidate["path"] not in selected_paths
                and total + candidate["size"] <= max_total_bytes
            ),
            None,
        )
        if item and len(selected) < sample_count:
            selected.append(item)
            selected_paths.add(item["path"])
            total += item["size"]

    for item in candidates:
        if len(selected) >= sample_count:
            break
        if item["path"] in selected_paths or total + item["size"] > max_total_bytes:
            continue
        selected.append(item)
        selected_paths.add(item["path"])
        total += item["size"]
    return selected


def _failed_report(
    *,
    snapshot: Path,
    started_at: str,
    started_timer: float,
    code: str,
    message: str,
    **details: Any,
) -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "performed_at": datetime.now(timezone.utc).isoformat(),
        "started_at": started_at,
        "scope": "canary",
        "result": "failed",
        "snapshot": str(snapshot),
        "duration_ms": round((time.perf_counter() - started_timer) * 1000),
        "rto_observed_seconds": round(time.perf_counter() - started_timer, 3),
        "checked_files": 0,
        "checked_bytes": 0,
        "temporary_content_removed": True,
        "issues": [{"code": code, "message": message, **details}],
    }


def run_restore_drill(
    workspace: str | Path,
    snapshot: str | Path,
    restore_root: str | Path,
    *,
    sample_count: int = 16,
    max_file_mb: int = 16,
    max_total_mb: int = 128,
    output: str | Path | None = None,
) -> dict[str, Any]:
    """Restore a deterministic, stratified sample into an isolated temp tree."""
    workspace_root = Path(workspace).expanduser().resolve()
    snapshot_root = Path(snapshot).expanduser().resolve()
    target_root = Path(restore_root).expanduser().resolve()
    started_at = datetime.now(timezone.utc).isoformat()
    started_timer = time.perf_counter()
    if sample_count < 1 or max_file_mb < 1 or max_total_mb < 1:
        raise ValueError("Restore drill limits must be positive.")
    if not snapshot_root.is_dir():
        raise ValueError(f"Snapshot does not exist: {snapshot_root}")
    if target_root == Path(target_root.anchor):
        raise ValueError("Restore drill root cannot be a filesystem root.")
    if target_root == workspace_root or workspace_root in target_root.parents:
        raise ValueError("Restore drill root cannot be inside the live Workspace.")
    if target_root == snapshot_root or snapshot_root in target_root.parents:
        raise ValueError("Restore drill root cannot be inside the source snapshot.")

    report_path = (
        Path(output)
        if output
        else workspace_root / "08_Indexes" / "RecoveryDrills" / "latest-restore-drill.json"
    )
    verification_path = (
        workspace_root / "08_Indexes" / "BackupVerification" / "latest-snapshot-verification.json"
    )
    try:
        verification = _read_json(verification_path)
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, ValueError):
        verification = {}
    verification_snapshot = Path(str(verification.get("snapshot") or "")).resolve()
    if not verification.get("valid") or verification_snapshot != snapshot_root:
        report = _failed_report(
            snapshot=snapshot_root,
            started_at=started_at,
            started_timer=started_timer,
            code="VERIFICATION_EVIDENCE_MISSING",
            message="Latest valid verification evidence does not match the requested snapshot.",
        )
        _atomic_json(report_path, report)
        return report

    manifest_path = snapshot_root / MANIFEST_NAME
    try:
        manifest = _read_json(manifest_path)
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
        report = _failed_report(
            snapshot=snapshot_root,
            started_at=started_at,
            started_timer=started_timer,
            code="MANIFEST_UNREADABLE",
            message="Snapshot manifest is missing or unreadable.",
            error=str(exc),
        )
        _atomic_json(report_path, report)
        return report

    manifest_hash = _sha256(manifest_path)
    if verification.get("manifest_sha256") != manifest_hash:
        report = _failed_report(
            snapshot=snapshot_root,
            started_at=started_at,
            started_timer=started_timer,
            code="VERIFICATION_MANIFEST_MISMATCH",
            message="Verification evidence is not bound to the current snapshot manifest.",
        )
        _atomic_json(report_path, report)
        return report
    files = manifest.get("files")
    if not isinstance(files, list):
        report = _failed_report(
            snapshot=snapshot_root,
            started_at=started_at,
            started_timer=started_timer,
            code="MANIFEST_FILES_INVALID",
            message="Snapshot manifest file inventory is invalid.",
        )
        _atomic_json(report_path, report)
        return report

    selected = _select_canaries(
        files,
        seed=manifest_hash,
        sample_count=sample_count,
        max_file_bytes=max_file_mb * 1024 * 1024,
        max_total_bytes=max_total_mb * 1024 * 1024,
    )
    if not selected:
        report = _failed_report(
            snapshot=snapshot_root,
            started_at=started_at,
            started_timer=started_timer,
            code="NO_ELIGIBLE_CANARIES",
            message="No privacy-safe canary files satisfy the drill limits.",
        )
        _atomic_json(report_path, report)
        return report

    target_root.mkdir(parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix=".workspaceos-restore-drill-", dir=target_root))
    issues: list[dict[str, Any]] = []
    checked_bytes = 0
    category_counts: dict[str, int] = {}
    sample_ids: list[str] = []
    try:
        for item in selected:
            relative = item["path"]
            sample_id = hashlib.sha256(relative.encode("utf-8")).hexdigest()[:16]
            sample_ids.append(sample_id)
            source = _safe_member(snapshot_root, relative)
            destination = _safe_member(staging, relative)
            category = Path(relative).parts[0]
            category_counts[category] = category_counts.get(category, 0) + 1
            if not source.is_file() or is_link_or_reparse(source):
                issues.append({"code": "SOURCE_MISSING", "sample_id": sample_id})
                continue
            if source.stat().st_size != item.get("size") or _sha256(source) != item.get("sha256"):
                issues.append({"code": "SOURCE_HASH_MISMATCH", "sample_id": sample_id})
                continue
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, destination)
            if destination.stat().st_size != item["size"] or _sha256(destination) != item["sha256"]:
                issues.append({"code": "RESTORED_HASH_MISMATCH", "sample_id": sample_id})
                continue
            checked_bytes += item["size"]
    finally:
        # This directory was created by this function with a random name and is
        # never a user-selected destination. Remove transient restored content
        # after its read-back hash has been collected.
        shutil.rmtree(staging, ignore_errors=True)

    residuals = any(target_root.glob(".workspaceos-restore-drill-*"))
    if residuals:
        issues.append({"code": "TEMPORARY_CONTENT_REMAINS"})
    duration = time.perf_counter() - started_timer
    report = {
        "schema_version": SCHEMA_VERSION,
        "performed_at": datetime.now(timezone.utc).isoformat(),
        "started_at": started_at,
        "scope": "canary",
        "result": "passed" if not issues else "failed",
        "snapshot": str(snapshot_root),
        "snapshot_manifest_sha256": manifest_hash,
        "verification_report": str(verification_path),
        "selection_algorithm": "sha256-stratified-v1",
        "requested_samples": sample_count,
        "checked_files": len(selected) - len([item for item in issues if item["code"] != "TEMPORARY_CONTENT_REMAINS"]),
        "checked_bytes": checked_bytes,
        "categories": category_counts,
        "sample_ids": sample_ids,
        "duration_ms": round(duration * 1000),
        "rto_observed_seconds": round(duration, 3),
        "temporary_content_removed": not residuals,
        "contains_sample_paths": False,
        "issues": issues,
    }
    _atomic_json(report_path, report)
    return report
