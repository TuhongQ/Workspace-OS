"""Privacy-preserving checks for exposed credentials and unsafe links.

The report intentionally never contains matched secret material. It records
only the rule identifier, relative path, line number, and a remediation hint.
"""
from __future__ import annotations

import fnmatch
import json
import os
import re
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from path_safety import is_link_or_reparse

SCHEMA_VERSION = "1.0"
SEVERITY_RANK = {"INFO": 0, "WARNING": 1, "ERROR": 2, "CRITICAL": 3}
SKIP_DIRECTORIES = {
    ".git", ".pytest_cache", ".venv", ".vs", "__pycache__", "node_modules",
    "$recycle.bin", "#recycle", "@eadir",
}
SKIP_PREFIXES = {
    "08_indexes",
    "06_release/packages/_workspaceos_trash",
}
PROTECTED_NAMES = {"private", "accounts", "certificates", "secrets"}
TEXT_EXTENSIONS = {
    ".bat", ".cfg", ".cmd", ".conf", ".config", ".cs", ".env", ".go", ".ini",
    ".java", ".js", ".json", ".jsx", ".md", ".php", ".properties", ".ps1",
    ".py", ".rb", ".rs", ".sh", ".sql", ".toml", ".ts", ".tsx", ".txt",
    ".xml", ".yaml", ".yml",
}
TEXT_NAMES = {".env", ".npmrc", ".pypirc", "dockerfile", "makefile"}
EXPOSED_FILENAMES = {
    ".env", ".env.local", ".env.production", ".npmrc", ".pypirc",
    "id_rsa", "id_dsa", "id_ecdsa", "id_ed25519", "credentials.json",
}
EXPOSED_SUFFIXES = {".key", ".p12", ".pfx"}
PLACEHOLDER_TOKENS = {
    "", "changeme", "change-me", "example", "example-token", "fake", "none",
    "not-a-secret", "placeholder", "redacted", "sample", "secret", "test",
    "todo", "your-api-key", "your-token", "xxx", "xxxx",
}


RULES: tuple[tuple[str, str, re.Pattern[str], str], ...] = (
    (
        "PRIVATE_KEY_MATERIAL",
        "CRITICAL",
        re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH |DSA )?PRIVATE KEY-----"),
        "立即撤销或轮换对应密钥，并把私钥移到受保护的凭据存储。",
    ),
    (
        "AWS_ACCESS_KEY",
        "ERROR",
        re.compile(r"(?<![A-Z0-9])(?:AKIA|ASIA)[A-Z0-9]{16}(?![A-Z0-9])"),
        "轮换访问密钥，并改用系统凭据存储或短期身份令牌。",
    ),
    (
        "GITHUB_TOKEN",
        "ERROR",
        re.compile(r"(?<![A-Za-z0-9_])(?:gh[pousr]_[A-Za-z0-9]{30,255}|github_pat_[A-Za-z0-9_]{20,255})"),
        "撤销并轮换 GitHub Token，避免将其保存在 Workspace 文件中。",
    ),
    (
        "OPENAI_API_KEY",
        "ERROR",
        re.compile(r"(?<![A-Za-z0-9_-])sk-(?:proj-|svcacct-)?[A-Za-z0-9_-]{20,}"),
        "撤销并轮换 API Key，改用环境变量或系统凭据存储。",
    ),
    (
        "SLACK_TOKEN",
        "ERROR",
        re.compile(r"(?<![A-Za-z0-9])xox[baprs]-[A-Za-z0-9-]{20,}"),
        "撤销并轮换 Slack Token，改用受保护的凭据存储。",
    ),
    (
        "GOOGLE_API_KEY",
        "ERROR",
        re.compile(r"(?<![A-Za-z0-9_-])AIza[A-Za-z0-9_-]{30,}"),
        "限制并轮换 Google API Key，避免将其保存在 Workspace 文件中。",
    ),
    (
        "CREDENTIAL_IN_URI",
        "ERROR",
        re.compile(r"\b[a-z][a-z0-9+.-]{2,15}://[^/\s:@]+:[^/\s@]{6,}@"),
        "移除 URI 中的明文凭据并轮换密码，改用凭据提供器。",
    ),
)
GENERIC_ASSIGNMENT = re.compile(
    r"""(?ix)
    \b(?:api[_-]?key|access[_-]?token|auth[_-]?token|client[_-]?secret|
    password|passwd|secret[_-]?key)\b
    \s*(?:=|:)\s*
    ["']?([A-Za-z0-9_./+=:@!#$%^&*~-]{8,})["']?
    """
)


def _read_config(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8-sig"))
        return value if isinstance(value, dict) else {}
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return {}


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


def _is_protected(relative: Path) -> bool:
    return bool({part.lower() for part in relative.parts} & PROTECTED_NAMES)


def _is_skipped(relative: Path) -> bool:
    lowered = tuple(part.lower() for part in relative.parts)
    if any(part in SKIP_DIRECTORIES for part in lowered):
        return True
    normalized = relative.as_posix().lower()
    return any(normalized == prefix or normalized.startswith(prefix + "/") for prefix in SKIP_PREFIXES)


def _ignored(relative: str, code: str, config: dict[str, Any]) -> bool:
    for rule in config.get("ignore", []):
        if not isinstance(rule, dict):
            continue
        pattern = str(rule.get("path") or "")
        codes = rule.get("codes", ["*"])
        if isinstance(codes, str):
            codes = [codes]
        if pattern and fnmatch.fnmatch(relative.lower(), pattern.lower()) and (
            "*" in codes or code in codes
        ):
            return True
    return False


def _outside_root(path: Path, root: Path) -> tuple[bool, str | None]:
    try:
        target = path.resolve(strict=False)
        target.relative_to(root)
        return False, str(target)
    except (OSError, ValueError):
        try:
            return True, str(path.resolve(strict=False))
        except OSError:
            return True, None


def _looks_like_placeholder(value: str) -> bool:
    normalized = value.strip("\"'").lower()
    return (
        normalized in PLACEHOLDER_TOKENS
        or normalized.startswith(("${", "{{", "<"))
        or normalized.endswith(("}", "}}", ">"))
        or "example" in normalized
        or "placeholder" in normalized
        or "redacted" in normalized
    )


def audit_security(
    workspace: str | Path,
    *,
    config_path: str | Path | None = None,
    max_file_kb: int = 2048,
    max_findings: int = 500,
) -> dict[str, Any]:
    root = Path(workspace).expanduser().resolve()
    config_file = (
        Path(config_path).expanduser().resolve()
        if config_path
        else root / "07_Admin" / "WorkspaceOS" / "security-audit-ignore.json"
    )
    config = _read_config(config_file)
    findings: list[dict[str, Any]] = []
    scanned_files = skipped_large = skipped_protected = skipped_binary = unreadable = 0
    truncated = False

    def add(severity: str, code: str, relative: str, message: str, **detail: Any) -> None:
        nonlocal truncated
        if _ignored(relative, code, config):
            return
        if len(findings) >= max_findings:
            truncated = True
            return
        findings.append({
            "severity": severity,
            "code": code,
            "path": relative,
            "message": message,
            **detail,
        })

    for current, dirnames, filenames in os.walk(root, followlinks=False):
        current_path = Path(current)
        try:
            current_relative = current_path.relative_to(root)
        except ValueError:
            continue
        kept_directories: list[str] = []
        for name in dirnames:
            relative_path = current_relative / name
            if _is_skipped(relative_path):
                continue
            candidate = current_path / name
            relative = relative_path.as_posix()
            if is_link_or_reparse(candidate):
                outside, target = _outside_root(candidate, root)
                if outside:
                    add(
                        "ERROR", "LINK_ESCAPES_WORKSPACE", relative,
                        "符号链接或目录联接指向 Workspace 之外，可能绕过扫描、备份或隐私边界。",
                        target_available=target is not None,
                    )
                else:
                    add(
                        "WARNING", "REPARSE_POINT_SKIPPED", relative,
                        "目录链接或 reparse point 已从安全扫描中隔离。",
                    )
                continue
            kept_directories.append(name)
        dirnames[:] = kept_directories

        for name in filenames:
            path = current_path / name
            relative_path = current_relative / name
            relative = relative_path.as_posix()
            if _is_skipped(relative_path):
                continue
            if is_link_or_reparse(path):
                outside, target = _outside_root(path, root)
                if outside:
                    add(
                        "ERROR", "LINK_ESCAPES_WORKSPACE", relative,
                        "符号链接指向 Workspace 之外，可能绕过扫描、备份或隐私边界。",
                        target_available=target is not None,
                    )
                else:
                    add(
                        "WARNING", "REPARSE_POINT_SKIPPED", relative,
                        "文件链接或 reparse point 已从安全扫描中隔离。",
                    )
                continue
            if _is_protected(relative_path):
                skipped_protected += 1
                continue

            lowered_name = name.lower()
            if (
                lowered_name in EXPOSED_FILENAMES
                or Path(lowered_name).suffix in EXPOSED_SUFFIXES
            ) and not lowered_name.endswith((".example", ".sample", ".template")):
                add(
                    "WARNING", "SENSITIVE_FILENAME_EXPOSED", relative,
                    "疑似凭据或私钥文件位于受保护目录之外；请确认内容并迁移到 Private、Accounts、Certificates 或 secrets。",
                )

            try:
                size = path.stat().st_size
            except OSError:
                unreadable += 1
                add("WARNING", "SECURITY_FILE_UNREADABLE", relative, "安全审计无法读取该文件的元数据。")
                continue
            if size > max_file_kb * 1024:
                skipped_large += 1
                continue
            if path.suffix.lower() not in TEXT_EXTENSIONS and lowered_name not in TEXT_NAMES:
                skipped_binary += 1
                continue
            try:
                raw = path.read_bytes()
                if b"\x00" in raw[:4096]:
                    skipped_binary += 1
                    continue
                text = raw.decode("utf-8-sig", errors="replace")
            except OSError:
                unreadable += 1
                add("WARNING", "SECURITY_FILE_UNREADABLE", relative, "安全审计无法读取该文本文件。")
                continue
            scanned_files += 1
            for line_number, line in enumerate(text.splitlines(), 1):
                for code, severity, pattern, remediation in RULES:
                    if pattern.search(line):
                        add(severity, code, relative, remediation, line=line_number)
                for match in GENERIC_ASSIGNMENT.finditer(line):
                    if not _looks_like_placeholder(match.group(1)):
                        add(
                            "WARNING", "PLAINTEXT_CREDENTIAL_ASSIGNMENT", relative,
                            "发现疑似明文凭据赋值；请核实、轮换并改用环境变量或系统凭据存储。",
                            line=line_number,
                        )

    findings.sort(
        key=lambda item: (
            -SEVERITY_RANK[item["severity"]],
            item["path"],
            item.get("line", 0),
            item["code"],
        )
    )
    highest = max((SEVERITY_RANK[item["severity"]] for item in findings), default=0)
    status = "critical" if highest == 3 else "error" if highest == 2 else "warning" if highest == 1 else "healthy"
    return {
        "schema_version": SCHEMA_VERSION,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "workspace": str(root),
        "status": status,
        "privacy_mode": "redacted-findings-no-secret-values",
        "config": {
            "path": str(config_file),
            "loaded": bool(config),
        },
        "limits": {
            "max_file_kb": max_file_kb,
            "max_findings": max_findings,
        },
        "summary": {
            "scanned_files": scanned_files,
            "findings": len(findings),
            "critical": sum(item["severity"] == "CRITICAL" for item in findings),
            "error": sum(item["severity"] == "ERROR" for item in findings),
            "warning": sum(item["severity"] == "WARNING" for item in findings),
            "skipped_protected_files": skipped_protected,
            "skipped_large_files": skipped_large,
            "skipped_non_text_files": skipped_binary,
            "unreadable_files": unreadable,
            "truncated": truncated,
        },
        "findings": findings,
    }


def save_security_audit(report: dict[str, Any], output: str | Path) -> tuple[Path, Path]:
    json_path = _atomic_json(Path(output), report)
    md_path = json_path.with_suffix(".md")
    lines = [
        "# Workspace OS 安全暴露审计",
        "",
        f"- 状态：**{report['status'].upper()}**",
        f"- 生成时间：{report['generated_at']}",
        f"- 已扫描文本文件：{report['summary']['scanned_files']}",
        f"- 发现项：{report['summary']['findings']}",
        "- 隐私模式：报告不包含任何命中的 Token、密码或私钥内容。",
        "",
        "## 发现",
        "",
    ]
    if report["findings"]:
        for item in report["findings"]:
            location = f":{item['line']}" if item.get("line") else ""
            lines.append(
                f"- **{item['severity']}** `{item['code']}` "
                f"`{item['path']}{location}` — {item['message']}"
            )
    else:
        lines.append("- 未发现高置信度的凭据暴露或越界链接。")
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
