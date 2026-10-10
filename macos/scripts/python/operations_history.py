"""Privacy-minimised, tamper-evident operational history and rolling SLOs."""
from __future__ import annotations

import hashlib
import json
import math
import os
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

SCHEMA_VERSION = "1.0"
GENESIS_HASH = "0" * 64
LOCAL_ZONE = timezone(timedelta(hours=8), name="Asia/Shanghai")
SIGNAL_OBJECTIVES = {
    "search_available": 0.95,
    "snapshot_trusted": 1.0,
    "maintenance_integrity": 1.0,
    "evidence_valid": 1.0,
    "scheduled_tasks_healthy": 0.95,
}


def _read_object(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8-sig"))
        return value if isinstance(value, dict) else {}
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return {}


def _canonical(value: Any) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def _hash(value: Any) -> str:
    return hashlib.sha256(_canonical(value)).hexdigest()


def _timestamp(value: Any) -> datetime | None:
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        return parsed.replace(tzinfo=timezone.utc) if parsed.tzinfo is None else parsed
    except (TypeError, ValueError):
        return None


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


def operations_paths(workspace: str | Path) -> tuple[Path, Path, Path, Path]:
    root = Path(workspace).expanduser().resolve() / "08_Indexes" / "Operations"
    return (
        root / "records",
        root / "head.json",
        root / "operations-history-status.json",
        root / "operational-slo.json",
    )


def _current_signals(root: Path) -> tuple[dict[str, bool], dict[str, int]]:
    indexes = root / "08_Indexes"
    search = _read_object(indexes / "Search" / "search-status.json")
    recovery = _read_object(indexes / "Recovery" / "recovery-readiness.json")
    maintenance = _read_object(indexes / "Health" / "maintenance-audit.json")
    evidence = _read_object(indexes / "Evidence" / "status.json")
    tasks = _read_object(indexes / "Health" / "scheduled-tasks.json")
    alerts = _read_object(indexes / "Alerts" / "control-plane.json")
    alert_summary = alerts.get("summary") or {}
    signals = {
        "search_available": bool(search.get("available")),
        "snapshot_trusted": bool((recovery.get("evidence") or {}).get("snapshot_trusted")),
        "maintenance_integrity": maintenance.get("status") == "healthy",
        "evidence_valid": bool(evidence.get("valid")),
        "scheduled_tasks_healthy": bool(tasks.get("healthy")),
    }
    measures = {
        "recovery_score": int(recovery.get("score") or 0),
        "alerts_warning": int(alert_summary.get("WARNING") or 0),
        "alerts_error": int(alert_summary.get("ERROR") or 0),
        "alerts_critical": int(alert_summary.get("CRITICAL") or 0),
    }
    return signals, measures


def _load_records(records_dir: Path) -> list[tuple[Path, dict[str, Any]]]:
    records: list[tuple[Path, dict[str, Any]]] = []
    for path in sorted(records_dir.glob("*.json")) if records_dir.is_dir() else []:
        records.append((path, _read_object(path)))
    return records


def verify_operations_history(
    workspace: str | Path,
    *,
    output: str | Path | None = None,
) -> dict[str, Any]:
    records_dir, head_path, default_output, _ = operations_paths(workspace)
    issues: list[dict[str, Any]] = []
    previous = GENESIS_HASH
    expected_sequence = 1
    records = _load_records(records_dir)
    latest_hash = None
    for path, record in records:
        sequence = record.get("sequence")
        claimed = str(record.get("record_hash") or "")
        if sequence != expected_sequence:
            issues.append({
                "code": "OPERATIONS_SEQUENCE_INVALID",
                "file": path.name,
                "expected": expected_sequence,
                "actual": sequence,
            })
        if record.get("previous_hash") != previous:
            issues.append({"code": "OPERATIONS_PREVIOUS_HASH_MISMATCH", "file": path.name})
        body = {key: value for key, value in record.items() if key != "record_hash"}
        calculated = _hash(body)
        if claimed != calculated:
            issues.append({"code": "OPERATIONS_RECORD_HASH_MISMATCH", "file": path.name})
        previous = claimed
        latest_hash = claimed
        expected_sequence += 1

    head = _read_object(head_path)
    if records:
        last_path, last_record = records[-1]
        if (
            head.get("latest_sequence") != last_record.get("sequence")
            or head.get("latest_hash") != latest_hash
            or head.get("latest_record") != last_path.name
        ):
            issues.append({"code": "OPERATIONS_HEAD_MISMATCH"})
    elif head_path.is_file() and head:
        issues.append({"code": "OPERATIONS_HEAD_WITHOUT_RECORDS"})
    report = {
        "schema_version": SCHEMA_VERSION,
        "checked_at": datetime.now(timezone.utc).isoformat(),
        "status": "invalid" if issues else "valid" if records else "empty",
        "valid": not issues,
        "record_count": len(records),
        "latest_sequence": records[-1][1].get("sequence") if records else None,
        "latest_hash": latest_hash,
        "issues": issues,
    }
    _atomic_json(Path(output) if output else default_output, report)
    return report


def build_operational_slo(
    records: list[dict[str, Any]],
    *,
    current_signals: dict[str, bool],
    now: datetime,
    window_days: int = 30,
) -> dict[str, Any]:
    if window_days < 1:
        raise ValueError("window_days must be at least 1")
    cutoff = now.astimezone(LOCAL_ZONE).date() - timedelta(days=max(1, window_days) - 1)
    daily: dict[str, dict[str, Any]] = {}
    for record in records:
        day = str(record.get("local_day") or "")
        try:
            day_value = datetime.strptime(day, "%Y-%m-%d").date()
        except ValueError:
            continue
        if day_value < cutoff:
            continue
        previous = daily.get(day)
        if previous is None or int(record.get("sequence") or 0) > int(previous.get("sequence") or 0):
            daily[day] = record
    ordered = [daily[key] for key in sorted(daily)]
    sample_days = len(ordered)
    metrics: dict[str, Any] = {}
    findings: list[dict[str, Any]] = []
    if sample_days < 7:
        findings.append({
            "severity": "INFO",
            "code": "OPERATIONS_HISTORY_INSUFFICIENT",
            "message": f"运维历史仅覆盖 {sample_days} 天；至少 7 天后启用趋势故障预算告警",
        })
    for signal, target in SIGNAL_OBJECTIVES.items():
        successes = sum(bool((record.get("signals") or {}).get(signal)) for record in ordered)
        failures = sample_days - successes
        actual = successes / sample_days if sample_days else None
        allowed_failures = math.floor(sample_days * (1.0 - target) + 1e-9)
        consecutive = 0
        for record in reversed(ordered):
            if bool((record.get("signals") or {}).get(signal)):
                break
            consecutive += 1
        exhausted = bool(sample_days >= 7 and failures > allowed_failures)
        metrics[signal] = {
            "target_percent": round(target * 100, 2),
            "actual_percent": round(actual * 100, 2) if actual is not None else None,
            "sample_days": sample_days,
            "successful_days": successes,
            "failed_days": failures,
            "allowed_failed_days": allowed_failures,
            "remaining_failed_days": max(0, allowed_failures - failures),
            "budget_exhausted": exhausted,
            "consecutive_failed_days": consecutive,
            "current": bool(current_signals.get(signal)),
        }
        if exhausted:
            findings.append({
                "severity": "WARNING",
                "code": "OPERATIONS_ERROR_BUDGET_EXHAUSTED",
                "message": f"{signal} 的 {window_days} 天故障预算已耗尽",
                "signal": signal,
            })
        if consecutive >= 3:
            findings.append({
                "severity": "ERROR",
                "code": "OPERATIONS_CONSECUTIVE_FAILURES",
                "message": f"{signal} 已连续 {consecutive} 个观测日失败",
                "signal": signal,
                "consecutive_days": consecutive,
            })
    current_failed = sorted(signal for signal, value in current_signals.items() if not value)
    trend_findings = [
        item for item in findings if item["severity"] in {"WARNING", "ERROR", "CRITICAL"}
    ]
    status = (
        "degraded"
        if current_failed or trend_findings
        else "insufficient-data"
        if sample_days < 7
        else "healthy"
    )
    return {
        "schema_version": SCHEMA_VERSION,
        "generated_at": now.astimezone(timezone.utc).isoformat(),
        "status": status,
        "window_days": window_days,
        "sample_days": sample_days,
        "current_failed_signals": current_failed,
        "metrics": metrics,
        "findings": findings,
        "privacy": {
            "paths_included": False,
            "credentials_included": False,
            "business_file_metadata_included": False,
        },
    }


def append_operations_record(
    workspace: str | Path,
    *,
    window_days: int = 30,
    dedupe_minutes: int = 30,
    now: datetime | None = None,
) -> dict[str, Any]:
    if window_days < 1:
        raise ValueError("window_days must be at least 1")
    if dedupe_minutes < 0:
        raise ValueError("dedupe_minutes cannot be negative")
    root = Path(workspace).expanduser().resolve()
    records_dir, head_path, status_path, slo_path = operations_paths(root)
    verification = verify_operations_history(root, output=status_path)
    if not verification["valid"]:
        return {
            "schema_version": SCHEMA_VERSION,
            "status": "blocked",
            "issues": verification["issues"],
            "history": verification,
        }
    current = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    signals, measures = _current_signals(root)
    records = _load_records(records_dir)
    fingerprint = _hash({"signals": signals, "measures": measures})
    if records:
        latest = records[-1][1]
        latest_at = _timestamp(latest.get("recorded_at"))
        if (
            latest.get("fingerprint") == fingerprint
            and latest_at
            and current - latest_at.astimezone(timezone.utc) <= timedelta(minutes=dedupe_minutes)
        ):
            slo = build_operational_slo(
                [record for _, record in records],
                current_signals=signals,
                now=current,
                window_days=window_days,
            )
            _atomic_json(slo_path, slo)
            return {
                "schema_version": SCHEMA_VERSION,
                "status": "unchanged",
                "sequence": latest.get("sequence"),
                "record_hash": latest.get("record_hash"),
                "history": verification,
                "slo": slo,
            }
    sequence = int(records[-1][1].get("sequence") or 0) + 1 if records else 1
    previous_hash = str(records[-1][1].get("record_hash") or GENESIS_HASH) if records else GENESIS_HASH
    body = {
        "schema_version": SCHEMA_VERSION,
        "sequence": sequence,
        "recorded_at": current.isoformat(),
        "local_day": current.astimezone(LOCAL_ZONE).date().isoformat(),
        "previous_hash": previous_hash,
        "fingerprint": fingerprint,
        "signals": signals,
        "measures": measures,
        "privacy": {
            "paths_included": False,
            "credentials_included": False,
            "business_file_metadata_included": False,
        },
    }
    record_hash = _hash(body)
    record = {**body, "record_hash": record_hash}
    record_name = f"{sequence:020d}-{record_hash}.json"
    record_path = records_dir / record_name
    if record_path.exists():
        raise FileExistsError(f"Operational history record already exists: {record_path}")
    _atomic_json(record_path, record)
    _atomic_json(head_path, {
        "schema_version": SCHEMA_VERSION,
        "updated_at": current.isoformat(),
        "latest_sequence": sequence,
        "latest_hash": record_hash,
        "latest_record": record_name,
    })
    verification = verify_operations_history(root, output=status_path)
    all_records = [record for _, record in _load_records(records_dir)]
    slo = build_operational_slo(
        all_records,
        current_signals=signals,
        now=current,
        window_days=window_days,
    )
    _atomic_json(slo_path, slo)
    return {
        "schema_version": SCHEMA_VERSION,
        "status": "appended",
        "sequence": sequence,
        "record": str(record_path),
        "record_hash": record_hash,
        "history": verification,
        "slo": slo,
        "outputs": [str(status_path), str(slo_path)],
    }
