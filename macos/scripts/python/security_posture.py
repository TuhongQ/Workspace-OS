"""Evaluate normalized platform security evidence without changing permissions."""
from __future__ import annotations

import json
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

SCHEMA_VERSION = "1.0"
SEVERITY_RANK = {"INFO": 0, "WARNING": 1, "ERROR": 2, "CRITICAL": 3}
BROAD_PRINCIPAL_SIDS = {
    "S-1-1-0": "everyone",
    "S-1-5-11": "authenticated-users",
    "S-1-5-32-545": "built-in-users",
}
TRUSTED_OWNER_SIDS = {
    "S-1-5-18",
    "S-1-5-32-544",
}


def _read_json(path: Path) -> dict[str, Any] | None:
    try:
        value = json.loads(path.read_text(encoding="utf-8-sig"))
        return value if isinstance(value, dict) else None
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return None


def _atomic_json(path: Path, value: dict[str, Any]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
            json.dump(value, handle, ensure_ascii=False, indent=2)
        os.replace(temporary, path)
    except Exception:
        try:
            os.unlink(temporary)
        except OSError:
            pass
        raise
    return path


def evaluate_security_posture(
    workspace: str | Path,
    probe: dict[str, Any] | None,
) -> dict[str, Any]:
    root = Path(workspace).expanduser().resolve()
    findings: list[dict[str, Any]] = []

    def add(severity: str, code: str, message: str, path: str, **detail: Any) -> None:
        findings.append({
            "severity": severity,
            "code": code,
            "message": message,
            "path": path,
            **detail,
        })

    if not probe:
        add(
            "WARNING",
            "SECURITY_POSTURE_PROBE_MISSING",
            "安全态势探针缺失或不可读，ACL 与磁盘加密状态未经验证。",
            "08_Indexes/Security/security-posture-probe.json",
        )
        probe_status = "missing"
        paths: list[dict[str, Any]] = []
        volume: dict[str, Any] = {"query_status": "missing"}
    else:
        probe_status = str(probe.get("probe_status") or "unknown")
        paths = probe.get("protected_paths", []) if isinstance(probe.get("protected_paths"), list) else []
        volume = probe.get("volume") if isinstance(probe.get("volume"), dict) else {}
        if probe_status != "ok":
            add(
                "WARNING",
                "SECURITY_POSTURE_PROBE_INCOMPLETE",
                "安全态势探针未完整完成，部分 ACL 或磁盘加密证据不可用。",
                "08_Indexes/Security/security-posture-probe.json",
                probe_status=probe_status,
            )

    existing_paths = 0
    protected_acl_paths = 0
    broad_write_paths = 0
    broad_read_paths = 0
    for item in paths:
        relative = str(item.get("relative") or "").replace("\\", "/").strip("/")
        if not relative:
            continue
        if not item.get("exists"):
            continue
        existing_paths += 1
        if item.get("acl_query_status") != "ok":
            add(
                "WARNING",
                "PROTECTED_PATH_ACL_UNVERIFIED",
                "受保护目录 ACL 无法读取，当前权限边界未经验证。",
                relative,
            )
            continue
        if item.get("inheritance_protected") is True:
            protected_acl_paths += 1
        else:
            add(
                "WARNING",
                "PROTECTED_PATH_ACL_INHERITED",
                "受保护目录仍继承上级 ACL，未来上级权限变化可能扩大访问范围。",
                relative,
            )

        owner_sid = str(item.get("owner_sid") or "")
        owner_is_current_user = bool(item.get("owner_is_current_user"))
        if owner_sid and owner_sid not in TRUSTED_OWNER_SIDS and not owner_is_current_user:
            add(
                "WARNING",
                "PROTECTED_PATH_OWNER_UNEXPECTED",
                "受保护目录所有者不是当前用户、SYSTEM 或本机管理员组。",
                relative,
            )

        broad_write = set()
        broad_read = set()
        for rule in item.get("access", []):
            if not isinstance(rule, dict) or str(rule.get("access_type")).lower() != "allow":
                continue
            sid = str(rule.get("sid") or "").upper()
            principal = BROAD_PRINCIPAL_SIDS.get(sid)
            if not principal:
                continue
            if rule.get("can_write"):
                broad_write.add(principal)
            elif rule.get("can_read"):
                broad_read.add(principal)
        if broad_write:
            broad_write_paths += 1
            add(
                "ERROR",
                "PROTECTED_PATH_BROAD_WRITE",
                "宽泛主体可修改受保护目录；私密文件可能被读取、替换或删除。",
                relative,
                principal_classes=sorted(broad_write),
            )
        elif broad_read:
            broad_read_paths += 1
            add(
                "WARNING",
                "PROTECTED_PATH_BROAD_READ",
                "宽泛主体可读取受保护目录，机密性边界不足。",
                relative,
                principal_classes=sorted(broad_read),
            )

    volume_query_status = str(volume.get("query_status") or "missing")
    volume_evidence_source = str(volume.get("evidence_source") or "none")
    encryption_verified = False
    if volume_query_status == "ok":
        encryption_percentage = volume.get("encryption_percentage")
        protection_status = str(volume.get("protection_status") or "").lower()
        volume_status = str(volume.get("volume_status") or "").lower()
        encryption_verified = (
            protection_status in {"on", "1"}
            and volume_status in {"fullyencrypted", "fully encrypted"}
            and isinstance(encryption_percentage, (int, float))
            and encryption_percentage >= 100
        )
        if not encryption_verified:
            add(
                "ERROR",
                "WORKSPACE_VOLUME_ENCRYPTION_OFF",
                "Workspace 所在卷没有可验证的完整磁盘加密与保护状态。",
                str(volume.get("mount_point") or root.anchor or root),
                encryption_percentage=encryption_percentage,
            )
    else:
        add(
            "WARNING",
            "VOLUME_ENCRYPTION_EVIDENCE_UNAVAILABLE",
            "无法取得 Workspace 所在卷的可信加密状态；不能证明静态数据已加密。",
            str(volume.get("mount_point") or root.anchor or root),
            query_code=str(volume.get("query_code") or volume_query_status),
        )

    findings.sort(
        key=lambda item: (
            -SEVERITY_RANK[item["severity"]],
            item["code"],
            item["path"],
        )
    )
    highest = max((SEVERITY_RANK[item["severity"]] for item in findings), default=0)
    status = "critical" if highest == 3 else "error" if highest == 2 else "warning" if highest == 1 else "healthy"
    return {
        "schema_version": SCHEMA_VERSION,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "workspace": str(root),
        "status": status,
        "privacy_mode": "normalized-sids-no-user-identities",
        "probe": {
            "status": probe_status,
            "generated_at": probe.get("generated_at") if probe else None,
            "platform": probe.get("platform") if probe else None,
        },
        "summary": {
            "configured_paths": len(paths),
            "existing_paths": existing_paths,
            "acl_inheritance_protected_paths": protected_acl_paths,
            "broad_write_paths": broad_write_paths,
            "broad_read_paths": broad_read_paths,
            "volume_encryption_verified": encryption_verified,
            "volume_evidence_source": volume_evidence_source,
            "volume_evidence_age_hours": volume.get("evidence_age_hours"),
            "findings": len(findings),
            "critical": sum(item["severity"] == "CRITICAL" for item in findings),
            "error": sum(item["severity"] == "ERROR" for item in findings),
            "warning": sum(item["severity"] == "WARNING" for item in findings),
        },
        "findings": findings,
    }


def build_security_posture(
    workspace: str | Path,
    probe_path: str | Path,
) -> dict[str, Any]:
    return evaluate_security_posture(workspace, _read_json(Path(probe_path)))


def save_security_posture(report: dict[str, Any], output: str | Path) -> tuple[Path, Path]:
    json_path = _atomic_json(Path(output), report)
    md_path = json_path.with_suffix(".md")
    lines = [
        "# Workspace OS 安全态势审计",
        "",
        f"- 状态：**{report['status'].upper()}**",
        f"- 生成时间：{report['generated_at']}",
        f"- 现有受保护目录：{report['summary']['existing_paths']}",
        f"- ACL 已阻断继承：{report['summary']['acl_inheritance_protected_paths']}",
        f"- 宽泛写入目录：{report['summary']['broad_write_paths']}",
        f"- 磁盘加密证据：{'已验证' if report['summary']['volume_encryption_verified'] else '未验证'}",
        "- 隐私模式：报告只保存内置主体分类与 SID，不保存本机用户名。",
        "",
        "## 发现",
        "",
    ]
    if report["findings"]:
        lines.extend(
            f"- **{item['severity']}** `{item['code']}` `{item['path']}` — {item['message']}"
            for item in report["findings"]
        )
    else:
        lines.append("- 受保护目录 ACL 与磁盘加密证据均通过。")
    md_path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=f".{md_path.name}.", suffix=".tmp", dir=md_path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
            handle.write("\n".join(lines) + "\n")
        os.replace(temporary, md_path)
    except Exception:
        try:
            os.unlink(temporary)
        except OSError:
            pass
        raise
    return json_path, md_path
