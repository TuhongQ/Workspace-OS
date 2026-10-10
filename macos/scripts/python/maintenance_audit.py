"""Audit Windows maintenance task definitions against a portable policy."""
from __future__ import annotations

import hashlib
import json
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path, PureWindowsPath
from typing import Any

SCHEMA_VERSION = "1.0"
DANGEROUS_ACTION_TOKENS = {
    "-command",
    "-encodedcommand",
    "-enc",
    "-windowstyle",
}
EXPECTED_HOST_TOKENS = ["-NoProfile", "-ExecutionPolicy", "Bypass"]


def _read_object(path: str | Path) -> dict[str, Any]:
    value = json.loads(Path(path).read_text(encoding="utf-8-sig"))
    if not isinstance(value, dict):
        raise ValueError(f"JSON object required: {path}")
    return value


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _windows_path(value: str | Path) -> str:
    return str(PureWindowsPath(str(value).strip().strip('"'))).casefold()


def _normalise_token(value: Any) -> str:
    text = str(value)
    if "\\" in text or ":" in text:
        return _windows_path(text)
    return text.casefold()


def _account_name(value: Any) -> str:
    return str(value or "").replace("/", "\\").rsplit("\\", 1)[-1].casefold()


def _resolve_tokens(values: list[Any], context: dict[str, str]) -> list[str]:
    resolved: list[str] = []
    for value in values:
        text = str(value)
        for key, replacement in context.items():
            text = text.replace("${" + key + "}", replacement)
        resolved.append(text)
    return resolved


def _issue(severity: str, code: str, message: str, **details: Any) -> dict[str, Any]:
    return {"severity": severity, "code": code, "message": message, **details}


def audit_maintenance_tasks(
    task_report: str | Path | dict[str, Any],
    policy: str | Path | dict[str, Any],
    *,
    repository: str | Path,
    workspace: str | Path,
    snapshots: str | Path,
    nas: str | Path,
    restore_root: str | Path = r"D:\WorkspaceRestoreTests\Automated",
    expected_user: str | None = None,
) -> dict[str, Any]:
    observed = _read_object(task_report) if not isinstance(task_report, dict) else task_report
    expected = _read_object(policy) if not isinstance(policy, dict) else policy
    repo = Path(repository).expanduser().resolve()
    context = {
        "repository": str(repo),
        "workspace": str(Path(workspace).expanduser().resolve()),
        "snapshots": str(Path(snapshots).expanduser().resolve()),
        "nas": str(nas),
        "restore_root": str(Path(restore_root).expanduser().resolve()),
        "current_user": str(expected_user or ""),
    }
    findings: list[dict[str, Any]] = []
    if observed.get("schema_version") != "1.1":
        findings.append(_issue(
            "ERROR",
            "TASK_REPORT_SCHEMA_UNSUPPORTED",
            "计划任务状态报告版本不支持定义完整性审计",
        ))
    if expected.get("schema_version") != SCHEMA_VERSION:
        raise ValueError("Unsupported maintenance policy schema.")
    observed_tasks = {
        str(item.get("name")): item
        for item in observed.get("tasks", [])
        if isinstance(item, dict) and item.get("name")
    }
    expected_tasks = {
        str(item.get("name")): item
        for item in expected.get("tasks", [])
        if isinstance(item, dict) and item.get("name")
    }
    for name in sorted(set(expected_tasks) - set(observed_tasks)):
        findings.append(_issue("ERROR", "MAINTENANCE_TASK_MISSING", "预期维护任务缺失", task=name))
    for name in sorted(set(observed_tasks) - set(expected_tasks)):
        findings.append(_issue("WARNING", "MAINTENANCE_TASK_UNEXPECTED", "发现策略外维护任务", task=name))
    if int(observed.get("task_count") or len(observed_tasks)) != len(observed_tasks):
        findings.append(_issue("ERROR", "TASK_REPORT_COUNT_MISMATCH", "计划任务报告计数与记录不一致"))

    principal_policy = expected.get("principal") or {}
    settings_policy = expected.get("settings") or {}
    for name in sorted(set(expected_tasks) & set(observed_tasks)):
        task = observed_tasks[name]
        definition = expected_tasks[name]
        if int(task.get("action_count") or 0) != 1:
            findings.append(_issue("ERROR", "TASK_ACTION_COUNT_INVALID", "维护任务必须且只能有一个动作", task=name))
        executable = PureWindowsPath(str(task.get("execute") or "")).name.casefold()
        if executable not in {"powershell.exe", "pwsh.exe"}:
            findings.append(_issue("ERROR", "TASK_EXECUTABLE_UNTRUSTED", "维护任务执行器不是 PowerShell", task=name))
        expected_script = repo / Path(str(definition.get("script") or ""))
        actual_script = str(task.get("script") or "")
        if not actual_script or _windows_path(actual_script) != _windows_path(expected_script):
            findings.append(_issue(
                "ERROR",
                "TASK_SCRIPT_MISMATCH",
                "维护任务脚本路径与策略不一致",
                task=name,
                expected=str(expected_script),
            ))
        elif not expected_script.is_file():
            findings.append(_issue("ERROR", "TASK_SCRIPT_MISSING", "策略指定脚本不存在", task=name))
        else:
            expected_hash = _sha256(expected_script)
            if str(task.get("script_sha256") or "").casefold() != expected_hash:
                findings.append(_issue("ERROR", "TASK_SCRIPT_HASH_MISMATCH", "任务报告中的脚本哈希与当前脚本不一致", task=name))

        host_tokens = [str(item) for item in (task.get("host_tokens") or [])]
        if [_normalise_token(item) for item in host_tokens] != [
            _normalise_token(item) for item in EXPECTED_HOST_TOKENS
        ]:
            findings.append(_issue(
                "CRITICAL",
                "TASK_HOST_ARGUMENTS_MISMATCH",
                "PowerShell 宿主参数与最小安全策略不一致",
                task=name,
            ))
        tokens = [str(item) for item in (task.get("argument_tokens") or [])]
        lowered_tokens = {
            _normalise_token(item)
            for item in [*host_tokens, *tokens]
        }
        dangerous = sorted(lowered_tokens & DANGEROUS_ACTION_TOKENS)
        if dangerous:
            findings.append(_issue(
                "CRITICAL",
                "TASK_DANGEROUS_ARGUMENT",
                "维护任务包含可执行任意命令的危险参数",
                task=name,
                arguments=dangerous,
            ))
        expected_arguments = _resolve_tokens(definition.get("arguments") or [], context)
        if [_normalise_token(item) for item in tokens] != [
            _normalise_token(item) for item in expected_arguments
        ]:
            findings.append(_issue(
                "ERROR",
                "TASK_ARGUMENTS_MISMATCH",
                "维护任务参数与策略不一致",
                task=name,
            ))

        principal = task.get("principal") or {}
        expected_principal_user = str(principal_policy.get("user") or "").replace(
            "${current_user}",
            str(expected_user or ""),
        )
        if not expected_principal_user or _account_name(principal.get("user")) != _account_name(
            expected_principal_user
        ):
            findings.append(_issue("CRITICAL", "TASK_PRINCIPAL_MISMATCH", "维护任务运行账户与策略不一致", task=name))
        if str(principal.get("logon_type") or "").casefold() != str(
            principal_policy.get("logon_type") or ""
        ).casefold():
            findings.append(_issue("ERROR", "TASK_LOGON_TYPE_MISMATCH", "维护任务登录类型与策略不一致", task=name))
        if str(principal.get("run_level") or "").casefold() != str(
            principal_policy.get("run_level") or ""
        ).casefold():
            findings.append(_issue("CRITICAL", "TASK_RUN_LEVEL_MISMATCH", "维护任务运行权限级别与策略不一致", task=name))

        if int(task.get("trigger_count") or 0) != 1:
            findings.append(_issue("ERROR", "TASK_TRIGGER_COUNT_INVALID", "维护任务必须且只能有一个触发器", task=name))
        trigger = ((task.get("triggers") or [{}]) or [{}])[0]
        expected_trigger = definition.get("trigger") or {}
        for field in ("type", "time", "interval"):
            if str(trigger.get(field)) != str(expected_trigger.get(field)):
                findings.append(_issue(
                    "ERROR",
                    "TASK_TRIGGER_MISMATCH",
                    "维护任务触发器与策略不一致",
                    task=name,
                    field=field,
                ))
        if expected_trigger.get("type") == "weekly" and int(
            trigger.get("days_of_week") or 0
        ) != int(expected_trigger.get("days_of_week") or 0):
            findings.append(_issue("ERROR", "TASK_TRIGGER_MISMATCH", "维护任务星期设置与策略不一致", task=name, field="days_of_week"))

        settings = task.get("settings") or {}
        if str(settings.get("execution_time_limit") or "") != str(
            settings_policy.get("execution_time_limit") or ""
        ):
            findings.append(_issue("WARNING", "TASK_TIME_LIMIT_MISMATCH", "维护任务执行时限与策略不一致", task=name))
        if bool(settings.get("start_when_available")) != bool(
            settings_policy.get("start_when_available")
        ):
            findings.append(_issue("WARNING", "TASK_START_POLICY_MISMATCH", "维护任务补跑策略与策略不一致", task=name))

    rank = {"INFO": 0, "WARNING": 1, "ERROR": 2, "CRITICAL": 3}
    highest = max((rank[item["severity"]] for item in findings), default=0)
    status = "critical" if highest == 3 else "error" if highest == 2 else "warning" if highest == 1 else "healthy"
    canonical_policy = json.dumps(expected, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return {
        "schema_version": SCHEMA_VERSION,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "status": status,
        "policy_sha256": hashlib.sha256(canonical_policy).hexdigest(),
        "task_report": str(task_report) if not isinstance(task_report, dict) else None,
        "policy": str(policy) if not isinstance(policy, dict) else None,
        "context": context,
        "summary": {
            "expected_tasks": len(expected_tasks),
            "observed_tasks": len(observed_tasks),
            "findings": len(findings),
            "critical": sum(item["severity"] == "CRITICAL" for item in findings),
            "error": sum(item["severity"] == "ERROR" for item in findings),
            "warning": sum(item["severity"] == "WARNING" for item in findings),
        },
        "findings": findings,
    }


def save_maintenance_audit(report: dict[str, Any], output: str | Path) -> Path:
    target = Path(output)
    target.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=f".{target.name}.", suffix=".tmp", dir=target.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
            json.dump(report, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, target)
    except Exception:
        try:
            os.unlink(temporary)
        except OSError:
            pass
        raise
    return target
