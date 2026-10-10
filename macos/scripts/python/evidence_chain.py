"""Tamper-evident control-plane evidence records.

Only metadata for derived Workspace OS reports is recorded: relative path,
presence, size, and SHA-256. File contents and absolute paths never enter the
chain.
"""
from __future__ import annotations

import hashlib
import json
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

SCHEMA_VERSION = "1.0"
GENESIS_HASH = "0" * 64
DEFAULT_EVIDENCE_PATHS = (
    "08_Indexes/Health/workspace-health.json",
    "08_Indexes/Alerts/control-plane.json",
    "08_Indexes/Recovery/recovery-readiness.json",
    "08_Indexes/Recovery/snapshot-export.json",
    "08_Indexes/Security/change-guard.json",
    "08_Indexes/Security/security-audit.json",
    "08_Indexes/Security/security-posture.json",
    "08_Indexes/Security/acl-hardening.json",
    "08_Indexes/Security/encryption-evidence.json",
    "08_Indexes/Health/scheduled-tasks.json",
    "08_Indexes/Health/maintenance-audit.json",
    "08_Indexes/AutomationDrills/latest-maintenance-integrity-drill.json",
    "08_Indexes/Operations/operations-history-status.json",
    "08_Indexes/Operations/operational-slo.json",
    "08_Indexes/OperationsDrills/latest-operations-history-drill.json",
    "08_Indexes/Devices/local-device-manifest.json",
    "08_Indexes/BackupVerification/latest-snapshot-verification.json",
    "08_Indexes/Recovery/latest-recovery-kit.json",
    "08_Indexes/Recovery/recovery-kit-retention.json",
    "08_Indexes/Release/latest-distribution.json",
    "08_Indexes/RecoveryDrills/latest-restore-drill.json",
    "08_Indexes/Devices/device-apply-status.json",
    "08_Indexes/Devices/device-bundle-import.json",
    "08_Indexes/Search/search-status.json",
)


def _canonical(value: Any) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


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


def _load_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(value, dict):
        raise ValueError(f"JSON object required: {path.name}")
    return value


def _normalise_relative(value: str) -> str:
    candidate = value.replace("\\", "/").strip("/")
    if not candidate or candidate.startswith("../") or "/../" in f"/{candidate}/":
        raise ValueError(f"Evidence path must stay inside the workspace: {value}")
    return candidate


def _artifact_metadata(root: Path, relative: str) -> dict[str, Any]:
    normalised = _normalise_relative(relative)
    path = root.joinpath(*normalised.split("/"))
    try:
        resolved = path.resolve(strict=False)
        resolved.relative_to(root)
    except (OSError, ValueError) as exc:
        raise ValueError(f"Evidence path escapes the workspace: {relative}") from exc
    if not path.is_file():
        return {"path": normalised, "present": False, "size": None, "sha256": None}
    return {
        "path": normalised,
        "present": True,
        "size": path.stat().st_size,
        "sha256": _sha256_file(path),
    }


def _issue(code: str, message: str, **details: Any) -> dict[str, Any]:
    return {"code": code, "message": message, **details}


def evidence_paths(workspace: str | Path) -> tuple[Path, Path, Path]:
    root = Path(workspace).expanduser().resolve()
    evidence = root / "08_Indexes" / "Evidence"
    return evidence / "records", evidence / "head.json", evidence / "status.json"


def verify_evidence_chain(
    workspace: str | Path,
    *,
    verify_current: bool = False,
    output: str | Path | None = None,
) -> dict[str, Any]:
    root = Path(workspace).expanduser().resolve()
    records_dir, head_path, default_status = evidence_paths(root)
    issues: list[dict[str, Any]] = []
    records: list[tuple[int, Path, dict[str, Any], str]] = []

    for path in sorted(records_dir.glob("*.json")) if records_dir.is_dir() else []:
        try:
            record = _load_json(path)
            sequence = int(record.get("sequence"))
            claimed_hash = str(record.get("record_hash") or "")
            records.append((sequence, path, record, claimed_hash))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError, TypeError, ValueError) as exc:
            issues.append(_issue("RECORD_UNREADABLE", "Evidence record is unreadable.", file=path.name, error=str(exc)))

    records.sort(key=lambda item: (item[0], item[1].name))
    if not records and not head_path.is_file():
        report = {
            "schema_version": SCHEMA_VERSION,
            "checked_at": datetime.now(timezone.utc).isoformat(),
            "status": "empty",
            "valid": True,
            "verify_current": verify_current,
            "record_count": 0,
            "latest_sequence": None,
            "latest_hash": None,
            "issues": issues,
        }
        _atomic_json(Path(output) if output else default_status, report)
        return report

    expected_previous = GENESIS_HASH
    expected_sequence = 1
    seen_sequences: set[int] = set()
    for sequence, path, record, claimed_hash in records:
        if sequence in seen_sequences:
            issues.append(_issue("DUPLICATE_SEQUENCE", "Evidence sequence is duplicated.", sequence=sequence))
        seen_sequences.add(sequence)
        if sequence != expected_sequence:
            issues.append(_issue(
                "SEQUENCE_GAP",
                "Evidence sequence is not continuous.",
                expected=expected_sequence,
                actual=sequence,
            ))
        expected_sequence = sequence + 1
        if record.get("schema_version") != SCHEMA_VERSION:
            issues.append(_issue("SCHEMA_INVALID", "Evidence record schema is unsupported.", sequence=sequence))
        if record.get("previous_hash") != expected_previous:
            issues.append(_issue("PREVIOUS_HASH_MISMATCH", "Evidence previous hash does not match.", sequence=sequence))
        artifacts = record.get("artifacts")
        if not isinstance(artifacts, list):
            issues.append(_issue("ARTIFACTS_INVALID", "Evidence artifact metadata is invalid.", sequence=sequence))
        elif record.get("artifacts_sha256") != _sha256_bytes(_canonical(artifacts)):
            issues.append(_issue("ARTIFACTS_HASH_MISMATCH", "Evidence artifact inventory hash does not match.", sequence=sequence))
        payload = {key: value for key, value in record.items() if key != "record_hash"}
        computed_hash = _sha256_bytes(_canonical(payload))
        if claimed_hash != computed_hash:
            issues.append(_issue("RECORD_HASH_MISMATCH", "Evidence record hash does not match.", sequence=sequence))
        expected_name = f"{sequence:020d}-{claimed_hash}.json"
        if path.name != expected_name:
            issues.append(_issue("RECORD_FILENAME_MISMATCH", "Evidence filename does not match its record.", sequence=sequence))
        expected_previous = claimed_hash

    head: dict[str, Any] | None = None
    try:
        head = _load_json(head_path)
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
        issues.append(_issue("HEAD_UNREADABLE", "Evidence head is missing or unreadable.", error=str(exc)))

    latest = records[-1] if records else None
    if head and latest:
        sequence, path, _, claimed_hash = latest
        if (
            head.get("latest_sequence") != sequence
            or head.get("latest_hash") != claimed_hash
            or head.get("record_file") != path.name
        ):
            issues.append(_issue("HEAD_MISMATCH", "Evidence head does not reference the latest record."))
    elif head and not latest:
        issues.append(_issue("HEAD_WITHOUT_RECORDS", "Evidence head exists without records."))

    if verify_current and latest:
        latest_artifacts = latest[2].get("artifacts", [])
        if isinstance(latest_artifacts, list):
            for expected in latest_artifacts:
                if not isinstance(expected, dict) or not isinstance(expected.get("path"), str):
                    continue
                try:
                    actual = _artifact_metadata(root, expected["path"])
                except (OSError, ValueError) as exc:
                    issues.append(_issue("CURRENT_READ_ERROR", "Current evidence artifact cannot be read.", path=expected.get("path"), error=str(exc)))
                    continue
                if actual != expected:
                    issues.append(_issue(
                        "CURRENT_HASH_MISMATCH",
                        "Current control-plane artifact differs from the latest evidence record.",
                        path=expected["path"],
                        expected_present=expected.get("present"),
                        actual_present=actual.get("present"),
                    ))

    report = {
        "schema_version": SCHEMA_VERSION,
        "checked_at": datetime.now(timezone.utc).isoformat(),
        "status": "valid" if not issues else "invalid",
        "valid": not issues,
        "verify_current": verify_current,
        "record_count": len(records),
        "latest_sequence": latest[0] if latest else None,
        "latest_hash": latest[3] if latest else None,
        "issues": issues,
    }
    _atomic_json(Path(output) if output else default_status, report)
    return report


def append_evidence_record(
    workspace: str | Path,
    *,
    event_type: str = "control-plane",
    subject: str = "daily-maintenance",
    paths: Iterable[str] | None = None,
) -> dict[str, Any]:
    root = Path(workspace).expanduser().resolve()
    records_dir, head_path, status_path = evidence_paths(root)
    preflight = verify_evidence_chain(root, output=status_path)
    if preflight["status"] == "invalid":
        raise ValueError("Evidence chain is invalid; refusing to append until it is investigated.")

    if preflight["status"] == "empty":
        sequence = 1
        previous_hash = GENESIS_HASH
    else:
        head = _load_json(head_path)
        sequence = int(head["latest_sequence"]) + 1
        previous_hash = str(head["latest_hash"])

    selected = tuple(paths) if paths is not None else DEFAULT_EVIDENCE_PATHS
    artifacts = [_artifact_metadata(root, item) for item in sorted({_normalise_relative(value) for value in selected})]
    payload: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "sequence": sequence,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "event_type": str(event_type),
        "subject": str(subject),
        "previous_hash": previous_hash,
        "artifacts": artifacts,
        "artifacts_sha256": _sha256_bytes(_canonical(artifacts)),
    }
    record_hash = _sha256_bytes(_canonical(payload))
    record = {**payload, "record_hash": record_hash}
    records_dir.mkdir(parents=True, exist_ok=True)
    record_path = records_dir / f"{sequence:020d}-{record_hash}.json"

    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    fd = os.open(record_path, flags, 0o600)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
            json.dump(record, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
    except Exception:
        try:
            record_path.unlink()
        except OSError:
            pass
        raise

    head = {
        "schema_version": SCHEMA_VERSION,
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "latest_sequence": sequence,
        "latest_hash": record_hash,
        "record_file": record_path.name,
    }
    _atomic_json(head_path, head)
    return {
        "status": "appended",
        "sequence": sequence,
        "record_hash": record_hash,
        "record": str(record_path),
        "head": str(head_path),
        "artifact_count": len(artifacts),
    }
