"""构建项目、客户分组与 Obsidian 知识链接关系图。"""
from __future__ import annotations

import json
import re
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from path_safety import is_link_or_reparse, iter_files_no_links

CACHE_NAMES = {".vs", "__pycache__", ".pytest_cache", "node_modules", ".venv"}
STATE_NAMES = {"Active", "Paused", "Completed", "Sandbox"}
PROJECT_HINTS = {"src", "source", "release", "footage", "inputs", "documents", "requirements"}
WIKI_LINK = re.compile(r"\[\[([^\]|#]+)(?:[|#][^\]]*)?\]\]")
STATUS = re.compile(r"当前状态[：:]\s*`?([A-Z]+)")


def _looks_like_project(path: Path) -> bool:
    try:
        names = {
            child.name.lower()
            for child in path.iterdir()
            if child.is_dir() and not is_link_or_reparse(child)
        }
    except OSError:
        return False
    return bool(names & PROJECT_HINTS) or (path / "STATUS.md").is_file()


def _project_roots(workspace: Path) -> list[tuple[Path, str | None, str]]:
    projects: list[tuple[Path, str | None, str]] = []
    project_space = workspace / "01_Projects"
    if not project_space.is_dir():
        return projects
    for state_dir in project_space.glob("*/*"):
        if (
            not state_dir.is_dir()
            or is_link_or_reparse(state_dir)
            or state_dir.name not in STATE_NAMES
        ):
            continue
        for first in state_dir.iterdir():
            if not first.is_dir() or is_link_or_reparse(first):
                continue
            nested = [
                child for child in first.iterdir()
                if child.is_dir()
                and not is_link_or_reparse(child)
                and _looks_like_project(child)
            ]
            if nested and not _looks_like_project(first):
                projects.extend((child, first.name, state_dir.name) for child in nested)
            else:
                projects.append((first, None, state_dir.name))
    return projects


def _project_metrics(path: Path) -> dict[str, Any]:
    count = total = 0
    extensions: Counter[str] = Counter()
    for item in iter_files_no_links(path):
        if not item.is_file() or {part.lower() for part in item.parts} & CACHE_NAMES:
            continue
        try:
            size = item.stat().st_size
        except OSError:
            continue
        count += 1
        total += size
        extensions[item.suffix.lower() or "(none)"] += 1
    status = "UNKNOWN"
    status_path = path / "STATUS.md"
    if status_path.is_file():
        match = STATUS.search(status_path.read_text(encoding="utf-8", errors="replace"))
        if match:
            status = match.group(1)
    return {
        "file_count": count,
        "total_bytes": total,
        "top_extensions": [{"extension": ext, "count": value} for ext, value in extensions.most_common(10)],
        "status": status,
    }


def build_workspace_graph(workspace: str | Path) -> dict[str, Any]:
    root = Path(workspace).expanduser().resolve()
    if not root.is_dir():
        raise ValueError(f"Workspace 不存在或不是目录: {root}")
    nodes: dict[str, dict[str, Any]] = {}
    edges: set[tuple[str, str, str]] = set()

    def node(identifier: str, kind: str, label: str, **properties: Any) -> None:
        nodes[identifier] = {"id": identifier, "kind": kind, "label": label, **properties}

    def edge(source: str, target: str, relation: str) -> None:
        edges.add((source, target, relation))

    node("workspace", "workspace", root.name, path=str(root))
    for category in sorted(
        path for path in root.iterdir()
        if path.is_dir()
        and not is_link_or_reparse(path)
        and re.match(r"^\d{2}_", path.name)
    ):
        identifier = f"category:{category.name}"
        node(identifier, "category", category.name, path=str(category))
        edge("workspace", identifier, "CONTAINS")

    project_nodes: list[tuple[str, Path, str]] = []
    for project_path, group, state in _project_roots(root):
        relative = project_path.relative_to(root).as_posix()
        project_name = f"{group}/{project_path.name}" if group else project_path.name
        identifier = f"project:{project_name}"
        metrics = _project_metrics(project_path)
        node(
            identifier,
            "project",
            project_name,
            path=str(project_path),
            relative=relative,
            lifecycle_state=state,
            **metrics,
        )
        edge("category:01_Projects", identifier, "CONTAINS")
        if group:
            group_id = f"group:{group}"
            if group_id not in nodes:
                node(group_id, "group", group)
                edge("category:01_Projects", group_id, "CONTAINS")
            edge(group_id, identifier, "GROUPS")
        project_nodes.append((identifier, project_path, project_name))

    vault = root / "02_Knowledge" / "ObsidianVault"
    notes_by_stem: dict[str, str] = {}
    note_text: dict[str, str] = {}
    if vault.is_dir():
        for path in sorted(
            path for path in iter_files_no_links(vault)
            if path.suffix.lower() == ".md"
        ):
            if {part.lower() for part in path.relative_to(vault).parts} & {"private", "secrets"}:
                continue
            relative = path.relative_to(vault).as_posix()
            identifier = f"note:{relative}"
            text = path.read_text(encoding="utf-8", errors="replace")
            node(identifier, "note", path.stem, path=str(path), relative=relative)
            edge("category:02_Knowledge", identifier, "CONTAINS")
            notes_by_stem.setdefault(path.stem.casefold(), identifier)
            note_text[identifier] = text
        for identifier, text in note_text.items():
            for target_name in WIKI_LINK.findall(text):
                target = notes_by_stem.get(Path(target_name.strip()).name.casefold())
                if target:
                    edge(identifier, target, "LINKS_TO")
        for project_id, project_path, project_name in project_nodes:
            project_tail = project_name.split("/")[-1].casefold()
            project_path_text = str(project_path).casefold()
            for note_id, text in note_text.items():
                note = nodes[note_id]
                if note["label"].casefold() == project_tail or project_path_text in text.casefold():
                    edge(note_id, project_id, "DOCUMENTS")

    graph_edges = [
        {"source": source, "target": target, "relation": relation}
        for source, target, relation in sorted(edges)
    ]
    counts = Counter(item["kind"] for item in nodes.values())
    return {
        "schema_version": "1.0",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "workspace": str(root),
        "summary": {
            "node_count": len(nodes),
            "edge_count": len(graph_edges),
            "kinds": dict(sorted(counts.items())),
        },
        "nodes": sorted(nodes.values(), key=lambda item: item["id"]),
        "edges": graph_edges,
    }


def save_workspace_graph(graph: dict[str, Any], output: str | Path) -> Path:
    target = Path(output)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(graph, ensure_ascii=False, indent=2), encoding="utf-8")
    return target
