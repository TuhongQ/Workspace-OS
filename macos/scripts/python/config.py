"""Workspace OS 配置加载器（仅依赖标准库）。"""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any


DEFAULTS: dict[str, Any] = {
    "workspace_name": "Workspace",
    "archive_after_days": 365,
    "large_file_mb": 1024,
    "log_retention_days": 90,
    "privacy_mode": "metadata-only",
    "default_project_type": "work",
    "device_name": os.environ.get("COMPUTERNAME") or os.environ.get("HOSTNAME") or "unknown",
}


def _scalar(value: str) -> Any:
    value = value.strip()
    if not value:
        return {}
    if (value.startswith('"') and value.endswith('"')) or (value.startswith("'") and value.endswith("'")):
        return value[1:-1]
    if value.lower() in {"true", "false"}:
        return value.lower() == "true"
    if value.lower() in {"null", "none", "~"}:
        return None
    try:
        return float(value) if "." in value else int(value)
    except ValueError:
        return value


def _minimal_yaml(text: str) -> dict[str, Any]:
    """解析本项目示例所用的安全 YAML 子集：映射、列表和标量。"""
    root: dict[str, Any] = {}
    stack: list[tuple[int, dict[str, Any]]] = [(-1, root)]
    for raw in text.splitlines():
        if not raw.strip() or raw.lstrip().startswith("#"):
            continue
        indent = len(raw) - len(raw.lstrip(" "))
        line = raw.strip()
        if ":" not in line:
            raise ValueError(f"不支持的 YAML 行: {raw}")
        key, value = line.split(":", 1)
        while stack[-1][0] >= indent:
            stack.pop()
        parent = stack[-1][1]
        parsed = _scalar(value)
        parent[key.strip()] = parsed
        if isinstance(parsed, dict):
            stack.append((indent, parsed))
    return root


def deep_merge(base: dict[str, Any], update: dict[str, Any]) -> dict[str, Any]:
    result = dict(base)
    for key, value in update.items():
        if isinstance(value, dict) and isinstance(result.get(key), dict):
            result[key] = deep_merge(result[key], value)
        else:
            result[key] = value
    return result


def load_config(path: str | Path | None = None) -> dict[str, Any]:
    config = dict(DEFAULTS)
    if path is None:
        env_path = os.environ.get("WORKSPACE_OS_CONFIG")
        path = Path(env_path) if env_path else None
    if not path:
        return config
    source = Path(path).expanduser()
    if not source.is_file():
        raise FileNotFoundError(f"配置文件不存在: {source}")
    text = source.read_text(encoding="utf-8-sig")
    try:
        loaded = json.loads(text)
    except json.JSONDecodeError:
        loaded = _minimal_yaml(text)
    if not isinstance(loaded, dict):
        raise ValueError("配置根节点必须是映射")
    return deep_merge(config, loaded)

