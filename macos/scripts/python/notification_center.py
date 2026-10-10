"""Create a privacy-minimized, deduplicated alert notification outbox."""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

SEVERITY_RANK = {"INFO": 0, "WARNING": 1, "ERROR": 2, "CRITICAL": 3}


def _read_json(path: Path) -> dict[str, Any] | None:
    try:
        value = json.loads(path.read_text(encoding="utf-8-sig"))
        return value if isinstance(value, dict) else None
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return None


def build_notification_bundle(
    control_plane: dict[str, Any],
    previous_state: dict[str, Any] | None = None,
    *,
    min_severity: str = "ERROR",
) -> dict[str, Any]:
    threshold = SEVERITY_RANK[min_severity.upper()]
    actionable = [
        {
            "id": item.get("id"),
            "severity": item.get("severity"),
            "source": item.get("source"),
            "code": item.get("code"),
            "message": item.get("message"),
        }
        for item in control_plane.get("alerts", [])
        if SEVERITY_RANK.get(str(item.get("severity", "")).upper(), -1) >= threshold
    ]
    actionable.sort(key=lambda item: (-SEVERITY_RANK[str(item["severity"]).upper()], str(item["source"]), str(item["code"])))
    identity = "|".join(f"{item['id']}:{item['severity']}:{item['code']}" for item in actionable)
    fingerprint = hashlib.sha256(identity.encode("utf-8")).hexdigest()[:24] if actionable else None
    previous_fingerprint = (previous_state or {}).get("last_delivered_fingerprint")
    status = "quiet" if not actionable else "unchanged" if fingerprint == previous_fingerprint else "pending"
    return {
        "schema_version": "1.0",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "status": status,
        "min_severity": min_severity.upper(),
        "fingerprint": fingerprint,
        "alert_count": len(actionable),
        "alerts": actionable,
        "privacy": {
            "paths_included": False,
            "credentials_included": False,
            "note": "Only severity, source, code, message, and opaque alert ID are exported.",
        },
    }


def create_notification_outbox(
    workspace: str | Path,
    output: str | Path,
    *,
    min_severity: str = "ERROR",
) -> tuple[dict[str, Any], Path]:
    root = Path(workspace).expanduser().resolve()
    control_plane_path = root / "08_Indexes" / "Alerts" / "control-plane.json"
    control_plane = _read_json(control_plane_path)
    if not control_plane:
        raise ValueError(f"控制平面报告缺失或不可读: {control_plane_path}")
    state_path = root / "08_Indexes" / "Alerts" / "notification-state.json"
    bundle = build_notification_bundle(control_plane, _read_json(state_path), min_severity=min_severity)
    output_path = Path(output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(bundle, ensure_ascii=False, indent=2), encoding="utf-8")
    return bundle, output_path
