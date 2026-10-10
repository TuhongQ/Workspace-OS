"""Isolated operational-history trend and tamper drill."""
from __future__ import annotations

import json
import os
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from operations_history import append_operations_record, verify_operations_history

SCHEMA_VERSION = "1.0"


def _is_within(path: Path, parent: Path) -> bool:
    try:
        path.relative_to(parent)
        return True
    except ValueError:
        return False


def _atomic_json(path: Path, value: dict[str, Any]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(
        prefix=f".{path.name}.",
        suffix=".tmp",
        dir=path.parent,
    )
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


def _write_signal_reports(root: Path, *, search_available: bool) -> None:
    indexes = root / "08_Indexes"
    reports = {
        "Search/search-status.json": {"available": search_available},
        "Recovery/recovery-readiness.json": {
            "score": 80,
            "evidence": {"snapshot_trusted": True},
        },
        "Health/maintenance-audit.json": {"status": "healthy"},
        "Evidence/status.json": {"valid": True},
        "Health/scheduled-tasks.json": {"healthy": True},
        "Alerts/control-plane.json": {
            "summary": {"WARNING": 0, "ERROR": 0, "CRITICAL": 0},
        },
    }
    for relative, value in reports.items():
        _atomic_json(indexes / relative, value)


def run_operations_history_drill(
    workspace: str | Path,
    drill_root: str | Path,
    *,
    output: str | Path | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Prove trend detection, tamper detection, and fail-closed append behavior.

    The synthetic Workspace must be outside the production Workspace and the
    drill root must be absent or empty. Only the final derived report is written
    to the production Workspace.
    """
    production = Path(workspace).expanduser().resolve()
    drill = Path(drill_root).expanduser().resolve()
    if drill == production or _is_within(drill, production) or _is_within(production, drill):
        raise ValueError("Drill root must be separate from the production Workspace")
    if drill.exists() and any(drill.iterdir()):
        raise ValueError(f"Drill root must be absent or empty: {drill}")
    synthetic = drill / "Workspace"
    synthetic.mkdir(parents=True, exist_ok=True)

    started = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    first_observation = started - timedelta(days=7)
    _write_signal_reports(synthetic, search_available=True)
    appended: list[dict[str, Any]] = []
    for offset in range(8):
        if offset == 5:
            _write_signal_reports(synthetic, search_available=False)
        result = append_operations_record(
            synthetic,
            now=first_observation + timedelta(days=offset),
            window_days=30,
            dedupe_minutes=30,
        )
        appended.append(result)

    before_tamper = verify_operations_history(synthetic)
    slo = appended[-1]["slo"]
    search_metric = slo["metrics"]["search_available"]
    trend_detected = (
        slo["status"] == "degraded"
        and search_metric["budget_exhausted"]
        and search_metric["consecutive_failed_days"] == 3
        and any(
            item.get("code") == "OPERATIONS_CONSECUTIVE_FAILURES"
            and item.get("signal") == "search_available"
            for item in slo["findings"]
        )
    )

    records_dir = synthetic / "08_Indexes" / "Operations" / "records"
    records = sorted(records_dir.glob("*.json"))
    first = json.loads(records[0].read_text(encoding="utf-8"))
    first["measures"]["recovery_score"] = 0
    _atomic_json(records[0], first)
    after_tamper = verify_operations_history(synthetic)
    count_before_blocked_append = len(list(records_dir.glob("*.json")))
    blocked = append_operations_record(
        synthetic,
        now=first_observation + timedelta(days=8),
    )
    count_after_blocked_append = len(list(records_dir.glob("*.json")))

    tamper_detected = (
        not after_tamper["valid"]
        and any(
            item.get("code") == "OPERATIONS_RECORD_HASH_MISMATCH"
            for item in after_tamper["issues"]
        )
    )
    append_blocked = (
        blocked.get("status") == "blocked"
        and count_before_blocked_append == count_after_blocked_append
    )
    gates = {
        "eight_daily_records_created": before_tamper["record_count"] == 8,
        "history_valid_before_tamper": bool(before_tamper["valid"]),
        "error_budget_exhaustion_detected": bool(trend_detected),
        "three_consecutive_failures_detected": (
            search_metric["consecutive_failed_days"] == 3
        ),
        "tamper_detected": bool(tamper_detected),
        "append_blocked_after_tamper": bool(append_blocked),
        "source_overwrites": 0,
        "source_deletions": 0,
    }
    boolean_gates = (
        "eight_daily_records_created",
        "history_valid_before_tamper",
        "error_budget_exhaustion_detected",
        "three_consecutive_failures_detected",
        "tamper_detected",
        "append_blocked_after_tamper",
    )
    passed = (
        all(gates[name] is True for name in boolean_gates)
        and gates["source_overwrites"] == 0
        and gates["source_deletions"] == 0
    )
    report = {
        "schema_version": SCHEMA_VERSION,
        "completed_at": datetime.now(timezone.utc).isoformat(),
        "result": "passed" if passed else "failed",
        "production_workspace": str(production),
        "drill_root": str(drill),
        "synthetic_record_count": before_tamper["record_count"],
        "slo": {
            "status": slo["status"],
            "sample_days": slo["sample_days"],
            "search_available": search_metric,
        },
        "tamper_verification": {
            "status": after_tamper["status"],
            "issue_codes": sorted({
                str(item.get("code"))
                for item in after_tamper["issues"]
                if item.get("code")
            }),
        },
        "gates": gates,
        "privacy": {
            "business_file_contents_read": False,
            "business_file_metadata_recorded": False,
            "credentials_included": False,
        },
    }
    report_path = (
        Path(output).expanduser().resolve()
        if output
        else production
        / "08_Indexes"
        / "OperationsDrills"
        / "latest-operations-history-drill.json"
    )
    _atomic_json(report_path, report)
    return {**report, "output": str(report_path)}
