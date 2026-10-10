"""隐私安全、事务式增量更新的 SQLite FTS5 本地搜索。"""
from __future__ import annotations

import json
import hashlib
import os
import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from path_safety import is_link_or_reparse
from version_detector import parse_version

TEXT_EXTENSIONS = {
    ".md", ".txt", ".py", ".ps1", ".sh", ".json", ".yaml", ".yml", ".toml",
    ".ini", ".cfg", ".csv", ".tsv", ".html", ".css", ".js", ".ts", ".tsx",
    ".jsx", ".c", ".cpp", ".h", ".hpp", ".cs", ".java", ".go", ".rs", ".sql",
    ".xml", ".log",
}
SKIP_NAMES = {
    ".git", ".vs", "__pycache__", ".pytest_cache", "node_modules", ".venv",
    ".ds_store", "thumbs.db",
}
SENSITIVE_NAMES = {"private", "accounts", "certificates", "secrets"}
DERIVED_PREFIXES = {"08_indexes"}
SCHEMA_VERSION = "1.1"
FTS_SCHEMA_VERSION = "2"


def _relative(path: Path, root: Path) -> str:
    return path.relative_to(root).as_posix()


def _excluded(path: Path, root: Path) -> bool:
    relative = _relative(path, root)
    lower_parts = {part.lower() for part in Path(relative).parts}
    lower = relative.lower()
    return bool(lower_parts & (SKIP_NAMES | SENSITIVE_NAMES)) or any(
        lower.startswith(prefix) for prefix in DERIVED_PREFIXES
    )


def _project_for(path: Path, root: Path) -> str | None:
    parts = path.relative_to(root).parts
    state_names = {"Active", "Paused", "Completed", "Sandbox"}
    for index, part in enumerate(parts):
        if part not in state_names or len(parts) <= index + 1:
            continue
        first = parts[index + 1]
        if len(parts) > index + 2:
            second = parts[index + 2]
            nested = root.joinpath(*parts[:index + 3])
            if (nested / "STATUS.md").is_file() or (nested / "README.md").is_file():
                return f"{first}/{second}"
        return first
    return None


def _read_text(path: Path, max_bytes: int) -> tuple[str, bool, str]:
    data = path.read_bytes()[: max_bytes + 1]
    truncated = len(data) > max_bytes
    data = data[:max_bytes]
    for encoding in ("utf-8-sig", "utf-16"):
        try:
            content = data.decode(encoding)
            return content, truncated, hashlib.sha256(
                content.encode("utf-8")
            ).hexdigest()
        except UnicodeDecodeError:
            continue
    content = data.decode("utf-8", errors="replace")
    return content, truncated, hashlib.sha256(
        content.encode("utf-8")
    ).hexdigest()


def _connect(database: Path) -> tuple[sqlite3.Connection, bool]:
    database.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(database)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA journal_mode=WAL")
    connection.execute("PRAGMA synchronous=FULL")
    connection.executescript(
        """
        CREATE TABLE IF NOT EXISTS metadata (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS documents (
            path TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            extension TEXT NOT NULL,
            size INTEGER NOT NULL,
            mtime_ns INTEGER NOT NULL,
            modified_time TEXT NOT NULL,
            category TEXT NOT NULL,
            project TEXT,
            status TEXT,
            version TEXT,
            archive_state TEXT NOT NULL,
            content_indexed INTEGER NOT NULL,
            content_truncated INTEGER NOT NULL,
            content_sha256 TEXT
        );
        """
    )
    document_columns = {
        row[1] for row in connection.execute("PRAGMA table_info(documents)")
    }
    if "content_sha256" not in document_columns:
        connection.execute("ALTER TABLE documents ADD COLUMN content_sha256 TEXT")
    columns = [row[1] for row in connection.execute("PRAGMA table_info(documents_fts)")]
    expected = ["path", "name", "project", "content"]
    rebuild_fts = columns != expected
    if rebuild_fts and columns:
        connection.execute("DROP TABLE documents_fts")
    connection.execute(
        """
        CREATE VIRTUAL TABLE IF NOT EXISTS documents_fts USING fts5(
            path,
            name,
            project,
            content,
            tokenize='unicode61 remove_diacritics 2'
        )
        """
    )
    return connection, rebuild_fts


def _last_good_path(database: Path) -> Path:
    return database.with_name(f"{database.stem}.last-good{database.suffix}")


def _atomic_json(path: Path, value: dict[str, Any]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(temporary, path)
    return path


def _remove_sqlite_family(path: Path) -> None:
    for candidate in (path, Path(f"{path}-wal"), Path(f"{path}-shm")):
        try:
            candidate.unlink()
        except FileNotFoundError:
            pass


def _sqlite_backup(source: Path, destination: Path) -> None:
    _remove_sqlite_family(destination)
    source_connection = sqlite3.connect(f"file:{source.as_posix()}?mode=ro", uri=True)
    destination_connection = sqlite3.connect(destination)
    try:
        source_connection.backup(destination_connection)
        destination_connection.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    finally:
        destination_connection.close()
        source_connection.close()


def check_search_database(database: str | Path) -> dict[str, Any]:
    db_path = Path(database).expanduser().resolve()
    issues: list[dict[str, Any]] = []
    if not db_path.is_file():
        return {
            "database": str(db_path),
            "valid": False,
            "status": "missing",
            "checked_at": datetime.now(timezone.utc).isoformat(),
            "total_files": 0,
            "content_files": 0,
            "issues": [{"code": "DATABASE_MISSING"}],
        }
    total = content = 0
    metadata: dict[str, str] = {}
    try:
        connection = sqlite3.connect(
            f"file:{db_path.as_posix()}?mode=ro",
            uri=True,
            timeout=5,
        )
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA query_only=ON")
        quick = [row[0] for row in connection.execute("PRAGMA quick_check")]
        if quick != ["ok"]:
            issues.append({"code": "SQLITE_QUICK_CHECK_FAILED", "details": quick[:10]})
        tables = {
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type IN ('table','view')"
            )
        }
        required = {"metadata", "documents", "documents_fts"}
        missing = sorted(required - tables)
        if missing:
            issues.append({"code": "TABLES_MISSING", "tables": missing})
        if not missing:
            metadata = dict(connection.execute("SELECT key,value FROM metadata"))
            document_columns = {
                row[1]
                for row in connection.execute("PRAGMA table_info(documents)")
            }
            if "content_sha256" not in document_columns:
                issues.append({"code": "CONTENT_HASH_COLUMN_MISSING"})
            total, content = connection.execute(
                "SELECT COUNT(*), COALESCE(SUM(content_indexed),0) FROM documents"
            ).fetchone()
            fts_total = connection.execute("SELECT COUNT(*) FROM documents_fts").fetchone()[0]
            if total != fts_total:
                issues.append({
                    "code": "FTS_DOCUMENT_COUNT_MISMATCH",
                    "documents": total,
                    "fts_documents": fts_total,
                })
            if "content_sha256" in document_columns:
                missing_hashes = connection.execute(
                    "SELECT COUNT(*) FROM documents "
                    "WHERE content_indexed = 1 AND "
                    "(content_sha256 IS NULL OR LENGTH(content_sha256) != 64)"
                ).fetchone()[0]
                if missing_hashes:
                    issues.append({
                        "code": "CONTENT_HASH_MISSING",
                        "documents": missing_hashes,
                    })
                mismatched_hashes = 0
                for row in connection.execute(
                    "SELECT d.content_sha256, f.content "
                    "FROM documents d JOIN documents_fts f ON f.path = d.path "
                    "WHERE d.content_indexed = 1"
                ):
                    actual_hash = hashlib.sha256(
                        str(row["content"]).encode("utf-8")
                    ).hexdigest()
                    if row["content_sha256"] != actual_hash:
                        mismatched_hashes += 1
                if mismatched_hashes:
                    issues.append({
                        "code": "FTS_CONTENT_HASH_MISMATCH",
                        "documents": mismatched_hashes,
                    })
            # Force an FTS index traversal without exposing or returning content.
            connection.execute(
                "SELECT rowid FROM documents_fts "
                "WHERE documents_fts MATCH 'workspaceos_integrity_probe' LIMIT 1"
            ).fetchall()
            if metadata.get("schema_version") != SCHEMA_VERSION:
                issues.append({
                    "code": "SCHEMA_VERSION_MISMATCH",
                    "actual": metadata.get("schema_version"),
                    "expected": SCHEMA_VERSION,
                })
            if metadata.get("fts_schema_version") != FTS_SCHEMA_VERSION:
                issues.append({
                    "code": "FTS_SCHEMA_VERSION_MISMATCH",
                    "actual": metadata.get("fts_schema_version"),
                    "expected": FTS_SCHEMA_VERSION,
                })
        connection.close()
    except (OSError, sqlite3.DatabaseError) as exc:
        issues.append({"code": "DATABASE_UNREADABLE", "error": str(exc)})
        try:
            connection.close()
        except (NameError, sqlite3.Error):
            pass
    return {
        "database": str(db_path),
        "valid": not issues,
        "status": "valid" if not issues else "invalid",
        "checked_at": datetime.now(timezone.utc).isoformat(),
        "schema_version": metadata.get("schema_version"),
        "fts_schema_version": metadata.get("fts_schema_version"),
        "workspace": metadata.get("workspace"),
        "generated_at": metadata.get("generated_at"),
        "privacy_mode": metadata.get("privacy_mode"),
        "total_files": total,
        "content_files": content,
        "issues": issues,
    }


def maintain_search_database(
    workspace: str | Path,
    database: str | Path,
    *,
    include_content: bool = False,
    max_content_kb: int = 1024,
    output: str | Path | None = None,
) -> dict[str, Any]:
    root = Path(workspace).expanduser().resolve()
    db_path = Path(database).expanduser().resolve()
    db_path.parent.mkdir(parents=True, exist_ok=True)
    fallback = _last_good_path(db_path)
    before = check_search_database(db_path)
    fallback_before = check_search_database(fallback)
    candidate = db_path.with_name(f".{db_path.name}.{uuid.uuid4().hex}.candidate.sqlite")
    last_good_candidate = fallback.with_name(f".{fallback.name}.{uuid.uuid4().hex}.candidate.sqlite")
    action = "incremental-promoted" if before["valid"] else "rebuilt"
    build_result: dict[str, Any] | None = None
    maintenance_issues: list[dict[str, Any]] = []
    promoted = False
    try:
        if before["valid"]:
            _sqlite_backup(db_path, candidate)
        build_result = build_search_database(
            root,
            candidate,
            include_content=include_content,
            max_content_kb=max_content_kb,
        )
        candidate_check = check_search_database(candidate)
        if not candidate_check["valid"]:
            raise sqlite3.DatabaseError(
                f"Candidate search index failed validation: {candidate_check['issues'][:3]}"
            )
        if before["valid"]:
            _sqlite_backup(db_path, last_good_candidate)
            last_good_check = check_search_database(last_good_candidate)
            if not last_good_check["valid"]:
                raise sqlite3.DatabaseError(
                    f"Last-good candidate failed validation: {last_good_check['issues'][:3]}"
                )
            os.replace(last_good_candidate, fallback)
        os.replace(candidate, db_path)
        promoted = True
    except (OSError, ValueError, sqlite3.DatabaseError) as exc:
        maintenance_issues.append({"code": "SEARCH_MAINTENANCE_FAILED", "error": str(exc)})
    finally:
        _remove_sqlite_family(candidate)
        _remove_sqlite_family(last_good_candidate)

    current = check_search_database(db_path)
    fallback_after = check_search_database(fallback)
    effective = current if current["valid"] else fallback_after
    available = bool(effective["valid"])
    using_fallback = bool(not current["valid"] and fallback_after["valid"])
    report = {
        "schema_version": "1.2",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "database": str(db_path),
        "last_good_database": str(fallback),
        "workspace": str(root),
        "status": (
            "healthy"
            if current["valid"] and promoted
            else "degraded"
            if available
            else "unavailable"
        ),
        "available": available,
        "current_valid": current["valid"],
        "last_good_valid": fallback_after["valid"],
        "using_fallback": using_fallback,
        "action": action if promoted else "kept-existing",
        "privacy_mode": effective.get("privacy_mode"),
        "total_files": effective.get("total_files", 0),
        "content_files": effective.get("content_files", 0),
        "content_hash_verified_files": (
            (build_result or {}).get("content_hash_verified_files", 0)
        ),
        "content_drift_detected": (
            (build_result or {}).get("content_drift_detected", 0)
        ),
        "link_entries_skipped": (
            (build_result or {}).get("link_entries_skipped", 0)
        ),
        "integrity_checked_at": current.get("checked_at"),
        "build": build_result,
        "current_issues": current.get("issues", []),
        "last_good_issues": fallback_after.get("issues", []),
        "maintenance_issues": maintenance_issues,
        "previous_current_valid": before["valid"],
        "previous_last_good_valid": fallback_before["valid"],
    }
    if output:
        _atomic_json(Path(output), report)
    return report


def build_search_database(
    workspace: str | Path,
    database: str | Path,
    include_content: bool = False,
    max_content_kb: int = 1024,
) -> dict[str, Any]:
    root = Path(workspace).expanduser().resolve()
    db_path = Path(database).expanduser().resolve()
    if not root.is_dir():
        raise ValueError(f"Workspace 不存在或不是目录: {root}")
    if max_content_kb <= 0:
        raise ValueError("内容索引上限必须大于 0 KiB")
    if db_path == root or not str(db_path).lower().endswith((".db", ".sqlite", ".sqlite3")):
        raise ValueError("搜索数据库必须使用 .db/.sqlite/.sqlite3 文件路径")

    connection, rebuild_fts = _connect(db_path)
    existing = {
        row["path"]: row
        for row in connection.execute(
            "SELECT path, size, mtime_ns, content_indexed, content_sha256 "
            "FROM documents"
        )
    }
    seen: set[str] = set()
    added = updated = unchanged = removed = content_files = excluded = 0
    content_drift_detected = 0
    link_entries_skipped = 0
    max_bytes = max_content_kb * 1024
    try:
        connection.execute("BEGIN IMMEDIATE")
        candidates: list[Path] = []
        for current, dirnames, filenames in os.walk(root, followlinks=False):
            current_path = Path(current)
            kept_directories = []
            for name in sorted(dirnames):
                path = current_path / name
                if is_link_or_reparse(path):
                    link_entries_skipped += 1
                    continue
                kept_directories.append(name)
            dirnames[:] = kept_directories
            for name in sorted(filenames):
                path = current_path / name
                if is_link_or_reparse(path):
                    link_entries_skipped += 1
                    continue
                candidates.append(path)
        for path in sorted(candidates):
            if not path.is_file():
                continue
            if _excluded(path, root):
                excluded += 1
                continue
            relative = _relative(path, root)
            if path.resolve() == db_path:
                continue
            try:
                stat = path.stat()
            except OSError:
                continue
            should_index_content = include_content and path.suffix.lower() in TEXT_EXTENSIONS
            previous = existing.get(relative)
            content = ""
            content_sha256 = None
            truncated = False
            if should_index_content:
                try:
                    content, truncated, content_sha256 = _read_text(
                        path,
                        max_bytes,
                    )
                    content_files += 1
                except OSError:
                    should_index_content = False
            if (
                previous
                and previous["size"] == stat.st_size
                and previous["mtime_ns"] == stat.st_mtime_ns
                and bool(previous["content_indexed"]) == should_index_content
                and (
                    not should_index_content
                    or previous["content_sha256"] == content_sha256
                )
                and not rebuild_fts
            ):
                unchanged += 1
                seen.add(relative)
                continue
            if (
                previous
                and should_index_content
                and previous["size"] == stat.st_size
                and previous["mtime_ns"] == stat.st_mtime_ns
                and previous["content_sha256"] != content_sha256
            ):
                content_drift_detected += 1
            parsed = parse_version(path)
            modified = datetime.fromtimestamp(stat.st_mtime, timezone.utc).isoformat()
            category = relative.split("/", 1)[0]
            values = (
                relative, path.name, path.suffix.lower(), stat.st_size, stat.st_mtime_ns,
                modified, category, _project_for(path, root), parsed["status"],
                parsed["version_text"], "archived" if "99_Archive" in path.parts else "active",
                int(should_index_content), int(truncated), content_sha256,
            )
            connection.execute(
                """
                INSERT INTO documents (
                    path,name,extension,size,mtime_ns,modified_time,category,project,
                    status,version,archive_state,content_indexed,content_truncated,
                    content_sha256
                ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                ON CONFLICT(path) DO UPDATE SET
                    name=excluded.name,extension=excluded.extension,size=excluded.size,
                    mtime_ns=excluded.mtime_ns,modified_time=excluded.modified_time,
                    category=excluded.category,project=excluded.project,status=excluded.status,
                    version=excluded.version,archive_state=excluded.archive_state,
                    content_indexed=excluded.content_indexed,
                    content_truncated=excluded.content_truncated,
                    content_sha256=excluded.content_sha256
                """,
                values,
            )
            connection.execute("DELETE FROM documents_fts WHERE path = ?", (relative,))
            project = _project_for(path, root)
            connection.execute(
                "INSERT INTO documents_fts(path,name,project,content) VALUES (?,?,?,?)",
                (relative, path.name, project or "", content),
            )
            if previous:
                updated += 1
            else:
                added += 1
            seen.add(relative)

        stale = set(existing) - seen
        for relative in stale:
            connection.execute("DELETE FROM documents WHERE path = ?", (relative,))
            connection.execute("DELETE FROM documents_fts WHERE path = ?", (relative,))
            removed += 1
        generated_at = datetime.now(timezone.utc).isoformat()
        metadata = {
            "schema_version": SCHEMA_VERSION,
            "workspace": str(root),
            "generated_at": generated_at,
            "privacy_mode": "local-content" if include_content else "metadata-only",
            "max_content_kb": str(max_content_kb),
            "fts_schema_version": FTS_SCHEMA_VERSION,
        }
        connection.executemany(
            "INSERT INTO metadata(key,value) VALUES (?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            metadata.items(),
        )
        connection.commit()
        connection.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        total = connection.execute("SELECT COUNT(*) FROM documents").fetchone()[0]
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()
    return {
        "database": str(db_path),
        "workspace": str(root),
        "privacy_mode": "local-content" if include_content else "metadata-only",
        "total_files": total,
        "content_files": content_files,
        "added": added,
        "updated": updated,
        "unchanged": unchanged,
        "removed": removed,
        "excluded": excluded,
        "content_hash_verified_files": content_files,
        "content_drift_detected": content_drift_detected,
        "link_entries_skipped": link_entries_skipped,
        "generated_at": generated_at,
    }


def _match_expression(query: str) -> str:
    terms = [term for term in query.strip().split() if term]
    return " AND ".join(f'"{term.replace(chr(34), chr(34) * 2)}"' for term in terms)


def search_database(
    database: str | Path,
    query: str = "",
    *,
    project: str | None = None,
    category: str | None = None,
    extension: str | None = None,
    status: str | None = None,
    archive_state: str | None = None,
    limit: int = 50,
) -> dict[str, Any]:
    requested_path = Path(database).expanduser().resolve()
    current_check = check_search_database(requested_path)
    fallback_path = _last_good_path(requested_path)
    fallback_check = check_search_database(fallback_path)
    if current_check["valid"]:
        db_path = requested_path
        using_fallback = False
    elif fallback_check["valid"]:
        db_path = fallback_path
        using_fallback = True
    else:
        raise ValueError(
            f"当前搜索数据库及上一代副本均不可用: {requested_path}"
        )
    if limit < 1 or limit > 500:
        raise ValueError("limit 必须在 1 到 500 之间")
    connection = sqlite3.connect(f"file:{db_path.as_posix()}?mode=ro", uri=True)
    connection.row_factory = sqlite3.Row
    clauses: list[str] = []
    parameters: list[Any] = []
    join = ""
    rank = "0.0 AS rank"
    if query.strip():
        join = "JOIN documents_fts f ON f.path = d.path"
        clauses.append("documents_fts MATCH ?")
        parameters.append(_match_expression(query))
        rank = "bm25(documents_fts, 4.0, 5.0, 6.0, 1.0) AS rank"
    for column, value in (
        ("project", project), ("category", category), ("extension", extension),
        ("status", status), ("archive_state", archive_state),
    ):
        if value is not None:
            clauses.append(f"LOWER(d.{column}) = LOWER(?)")
            parameters.append(value if column != "extension" or value.startswith(".") else f".{value}")
    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    rows = connection.execute(
        f"""
        SELECT d.path,d.name,d.extension,d.size,d.modified_time,d.category,d.project,
               d.status,d.version,d.archive_state,d.content_indexed,d.content_truncated,{rank}
        FROM documents d {join} {where}
        ORDER BY
            CASE WHEN d.project IS NOT NULL AND d.name IN ('README.md','STATUS.md') THEN 0
                 WHEN d.project IS NOT NULL THEN 1 ELSE 2 END,
            rank ASC,
            d.modified_time DESC
        LIMIT ?
        """,
        (*parameters, limit),
    ).fetchall()
    metadata = dict(connection.execute("SELECT key,value FROM metadata"))
    connection.close()
    return {
        "database": str(requested_path),
        "effective_database": str(db_path),
        "using_fallback": using_fallback,
        "query": query,
        "count": len(rows),
        "privacy_mode": metadata.get("privacy_mode"),
        "results": [dict(row) for row in rows],
    }


def search_status(database: str | Path) -> dict[str, Any]:
    db_path = Path(database).expanduser().resolve()
    current = check_search_database(db_path)
    fallback_path = _last_good_path(db_path)
    fallback = check_search_database(fallback_path)
    effective = current if current["valid"] else fallback
    available = bool(effective["valid"])
    using_fallback = bool(not current["valid"] and fallback["valid"])
    return {
        "database": str(db_path),
        "last_good_database": str(fallback_path),
        "available": available,
        "status": "healthy" if current["valid"] else "degraded" if available else "unavailable",
        "current_valid": current["valid"],
        "last_good_valid": fallback["valid"],
        "using_fallback": using_fallback,
        "schema_version": effective.get("schema_version"),
        "workspace": effective.get("workspace"),
        "generated_at": effective.get("generated_at"),
        "privacy_mode": effective.get("privacy_mode"),
        "total_files": effective.get("total_files", 0),
        "content_files": effective.get("content_files", 0),
        "integrity_checked_at": datetime.now(timezone.utc).isoformat(),
        "current_issues": current.get("issues", []),
        "last_good_issues": fallback.get("issues", []),
    }
