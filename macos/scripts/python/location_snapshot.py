"""生成电脑与 NAS 文件位置快照及可搜索的本地网页。"""
from __future__ import annotations

import html
import json
import os
import shutil
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from duplicate_finder import sha256_file
from path_safety import is_link_or_reparse

SKIP_PARTS = {
    "#recycle", "@eadir", "$recycle.bin", ".git", ".vs", "__pycache__",
    ".pytest_cache", "node_modules", ".venv", ".ds_store", ".spotlight-v100", ".fseventsd", ".trashes",
}
SKIP_DERIVED = {".workspace-os.json"}
APP_VERSION = "2.0.6"
TEMPLATE_VERSION = "2026.09.09-mac.1"


def _load_json(path: Path) -> dict[str, Any] | None:
    try:
        value = json.loads(path.read_text(encoding="utf-8-sig"))
        return value if isinstance(value, dict) else None
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return None


def _storage_usage(root: Path) -> dict[str, Any]:
    try:
        total, used, free = shutil.disk_usage(root)
        return {
            "available": True,
            "total": total,
            "used": used,
            "free": free,
            "percent": round((used / total * 100) if total else 0, 1),
        }
    except OSError as exc:
        return {"available": False, "error": str(exc)}


def _scan_tree(root: Path) -> tuple[dict[str, dict[str, Any]], set[str]]:
    files: dict[str, dict[str, Any]] = {}
    directories: set[str] = set()
    if not root.is_dir():
        return files, directories
    for current, dirnames, filenames in os.walk(root):
        current_path = Path(current)
        dirnames[:] = [
            name for name in dirnames
            if name.lower() not in SKIP_PARTS
            and not is_link_or_reparse(current_path / name)
        ]
        for name in dirnames:
            path = current_path / name
            try:
                directories.add(path.relative_to(root).as_posix())
            except (OSError, ValueError):
                continue
        for name in filenames:
            if name.lower() in SKIP_PARTS:
                continue
            path = current_path / name
            try:
                if is_link_or_reparse(path):
                    continue
                stat = path.stat()
                relative = path.relative_to(root).as_posix()
            except (OSError, ValueError):
                continue
            # 每台设备都会独立生成这些运行元数据；它们不同不代表用户文件冲突。
            if relative.lower().startswith("08_indexes/") or relative in SKIP_DERIVED:
                continue
            files[relative] = {
                "path": str(path),
                "parent": str(path.parent),
                "size": stat.st_size,
                "modified": datetime.fromtimestamp(stat.st_mtime, timezone.utc).isoformat(),
                "modified_ns": stat.st_mtime_ns,
            }
    return files, directories


def _scan(root: Path) -> dict[str, dict[str, Any]]:
    return _scan_tree(root)[0]


def _scan_directories(root: Path) -> set[str]:
    return _scan_tree(root)[1]


def _file_uri(path: str) -> str:
    try:
        candidate = Path(path)
        if not candidate.is_absolute():
            candidate = Path.cwd() / candidate
        return candidate.as_uri()
    except ValueError:
        return ""


def build_location_snapshot(
    computer: str | Path,
    nas: str | Path,
    hash_max_mb: int = 256,
    previous: dict[str, Any] | None = None,
    reuse_previous_nas: bool = False,
    refresh_nas_storage: bool = False,
) -> dict[str, Any]:
    computer_root = Path(computer).resolve()
    # abspath is lexical and does not issue a network stat against an SMB root.
    nas_root = Path(os.path.abspath(os.path.expanduser(str(nas))))
    local_files, local_directories = _scan_tree(computer_root)
    cached_nas_files = {
        item["relative"]: item["nas"]
        for item in (previous or {}).get("files", [])
        if item.get("nas")
    }
    if reuse_previous_nas and previous and cached_nas_files:
        nas_files = {
            item["relative"]: item["nas"]
            for item in previous.get("files", [])
            if item.get("nas")
        }
        nas_directories = {
            item["relative"]
            for item in previous.get("directories", [])
            if item.get("nas")
        }
        nas_scan_mode = "cached" if previous.get("nas_root") == str(nas_root) else "cached-alias"
        nas_metadata_at = previous.get("nas_metadata_at") or previous.get("generated_at")
    elif reuse_previous_nas:
        # Scheduled/offline-first refreshes must never fall back to a live SMB
        # traversal. An explicit --refresh-nas is required to rebuild metadata.
        nas_files, nas_directories = {}, set()
        nas_scan_mode = "cache-miss"
        nas_metadata_at = None
    else:
        nas_files, nas_directories = _scan_tree(nas_root)
        nas_scan_mode = "live"
        nas_metadata_at = datetime.now(timezone.utc).isoformat()
    try:
        nas_connected = nas_root.is_dir()
    except OSError:
        nas_connected = False
    records = []
    nas_files = {relative: record for relative, record in nas_files.items()
                 if Path(relative).name.casefold() not in SKIP_PARTS}
    previous_files = {item["relative"]: item for item in (previous or {}).get("files", [])}
    hash_limit = hash_max_mb * 1024 * 1024
    for relative in sorted(set(local_files) | set(nas_files)):
        local, remote = local_files.get(relative), nas_files.get(relative)
        if local and not remote:
            state, reason = "COMPUTER_ONLY", "仅电脑存在，适合作为当前工作文件；尚未进入 NAS。"
        elif remote and not local:
            state, reason = "NAS_ONLY", "仅 NAS 存在，需要时从 NAS 打开或复制到电脑。"
        else:
            assert local and remote
            old = previous_files.get(relative)
            old_local = old.get("computer") if old else None
            old_remote = old.get("nas") if old else None
            unchanged_since_previous = bool(
                old
                and old_local and old_remote
                and old_local.get("size") == local["size"]
                and old_remote.get("size") == remote["size"]
                and old_local.get("modified") == local["modified"]
                and old_remote.get("modified") == remote["modified"]
            )
            if unchanged_since_previous:
                state, reason = old["state"], old["reason"]
            elif local["size"] != remote["size"]:
                state, reason = "CONFLICT", "两边文件大小不同，需要人工选择版本。"
            elif reuse_previous_nas:
                state, reason = "BOTH_UNVERIFIED", "NAS 使用缓存元数据；电脑文件已变化，需要手动刷新 NAS 后核验。"
            elif local["size"] <= hash_limit:
                try:
                    same = sha256_file(local["path"]) == sha256_file(remote["path"])
                except OSError:
                    same = False
                state, reason = ("BOTH_SAME", "电脑和 NAS 内容一致。") if same else ("CONFLICT", "大小相同但内容哈希不同。")
            else:
                state, reason = "BOTH_UNVERIFIED", f"两边都有；文件超过 {hash_max_mb} MB，快照未计算完整哈希。"
        size = (local or remote or {}).get("size", 0)
        records.append({
            "relative": relative, "name": Path(relative).name, "extension": Path(relative).suffix.lower(),
            "size": size, "state": state, "reason": reason,
            "computer": local, "nas": remote,
            "computer_uri": _file_uri(local["parent"]) if local else "",
            "nas_uri": _file_uri(remote["parent"]) if remote else "",
        })
    counts = {state: sum(1 for record in records if record["state"] == state)
              for state in ("COMPUTER_ONLY", "NAS_ONLY", "BOTH_SAME", "BOTH_UNVERIFIED", "CONFLICT")}
    directories = [{"relative": relative, "computer": relative in local_directories, "nas": relative in nas_directories}
                   for relative in sorted(local_directories | nas_directories)]
    control_plane = _load_json(computer_root / "08_Indexes" / "Alerts" / "control-plane.json")
    search_status = _load_json(computer_root / "08_Indexes" / "Search" / "search-status.json")
    if not search_status:
        search_status = _load_json(computer_root / "08_Indexes" / "search-maintain.json")
    graph = _load_json(computer_root / "08_Indexes" / "Graph" / "workspace-graph.json")
    task_status = _load_json(computer_root / "08_Indexes" / "Health" / "scheduled-tasks.json")
    recovery = _load_json(computer_root / "08_Indexes" / "Recovery" / "recovery-readiness.json")
    if not recovery:
        recovery = _load_json(computer_root / "08_Indexes" / "recovery-readiness.json")
    security = _load_json(computer_root / "08_Indexes" / "Security" / "change-guard.json")
    security_audit = _load_json(computer_root / "08_Indexes" / "Security" / "security-audit.json")
    security_posture = _load_json(computer_root / "08_Indexes" / "Security" / "security-posture.json")
    acl_hardening = _load_json(
        computer_root / "08_Indexes" / "Security" / "acl-hardening.json"
    )
    device_manifest = _load_json(computer_root / "08_Indexes" / "Devices" / "local-device-manifest.json")
    device_sync = _load_json(computer_root / "08_Indexes" / "Devices" / "device-sync-status.json")
    device_apply = _load_json(computer_root / "08_Indexes" / "Devices" / "device-apply-status.json")
    evidence = _load_json(computer_root / "08_Indexes" / "Evidence" / "status.json")
    operations_history = _load_json(
        computer_root / "08_Indexes" / "Operations" / "operations-history-status.json"
    )
    operational_slo = _load_json(
        computer_root / "08_Indexes" / "Operations" / "operational-slo.json"
    )
    operations_drill = _load_json(
        computer_root
        / "08_Indexes"
        / "OperationsDrills"
        / "latest-operations-history-drill.json"
    )
    nas_storage = (
        _storage_usage(nas_root)
        if refresh_nas_storage or not reuse_previous_nas
        else (previous or {}).get("nas_storage", {"available": False, "error": "NAS capacity cache is unavailable."})
    )
    nas_metadata_status = {
        "live": "connected",
        "cached": "metadata-cached",
        "cached-alias": "metadata-cached",
        "cache-miss": "missing",
    }.get(nas_scan_mode, "missing")
    nas_capacity_status = (
        "connected" if nas_storage.get("available")
        else "capacity-unavailable" if nas_connected
        else "offline"
    )
    return {"schema_version": "2.8", "generated_at": datetime.now(timezone.utc).isoformat(),
            "app_version": APP_VERSION, "template_version": TEMPLATE_VERSION,
            "computer_root": str(computer_root), "nas_root": str(nas_root),
            "computer_storage": _storage_usage(computer_root),
            "nas_storage": nas_storage,
            "nas_connection_status": "connected" if nas_connected else "offline",
            "nas_metadata_status": nas_metadata_status,
            "nas_capacity_status": nas_capacity_status,
            "hash_max_mb": hash_max_mb, "counts": counts, "files": records, "directories": directories,
            "nas_scan_mode": nas_scan_mode,
            "nas_metadata_at": nas_metadata_at,
            "control_plane": control_plane,
            "search_status": search_status,
            "graph_summary": graph.get("summary") if graph else None,
            "task_status": task_status,
            "recovery_readiness": recovery,
            "device_manifest": (
                {
                    "generated_at": device_manifest.get("generated_at"),
                    "device_id": device_manifest.get("device_id"),
                    "status": device_manifest.get("status"),
                    "file_count": device_manifest.get("file_count"),
                    "total_bytes": device_manifest.get("total_bytes"),
                    "inventory_sha256": device_manifest.get("inventory_sha256"),
                    "scopes": device_manifest.get("scopes", []),
                }
                if device_manifest else None
            ),
            "device_sync_status": device_sync,
            "device_apply_status": device_apply,
            "evidence_chain": (
                {
                    "checked_at": evidence.get("checked_at"),
                    "status": evidence.get("status"),
                    "valid": evidence.get("valid"),
                    "record_count": evidence.get("record_count"),
                    "latest_sequence": evidence.get("latest_sequence"),
                    "latest_hash": evidence.get("latest_hash"),
                    "issue_count": len(evidence.get("issues", [])),
                }
                if evidence else None
            ),
            "operations": {
                "history": (
                    {
                        "checked_at": operations_history.get("checked_at"),
                        "status": operations_history.get("status"),
                        "valid": operations_history.get("valid"),
                        "record_count": operations_history.get("record_count"),
                        "latest_sequence": operations_history.get("latest_sequence"),
                        "issue_count": len(operations_history.get("issues", [])),
                    }
                    if operations_history else None
                ),
                "slo": (
                    {
                        "generated_at": operational_slo.get("generated_at"),
                        "status": operational_slo.get("status"),
                        "window_days": operational_slo.get("window_days"),
                        "sample_days": operational_slo.get("sample_days"),
                        "current_failed_signals": operational_slo.get(
                            "current_failed_signals", []
                        ),
                        "metrics": operational_slo.get("metrics", {}),
                        "findings": operational_slo.get("findings", []),
                    }
                    if operational_slo else None
                ),
                "drill": (
                    {
                        "completed_at": operations_drill.get("completed_at"),
                        "result": operations_drill.get("result"),
                        "synthetic_record_count": operations_drill.get(
                            "synthetic_record_count"
                        ),
                        "gates": operations_drill.get("gates", {}),
                    }
                    if operations_drill else None
                ),
            },
            "security_guard": (
                {
                    "generated_at": security.get("generated_at"),
                    "status": security.get("status"),
                    "summary": security.get("summary"),
                    "findings": security.get("findings", []),
                    "baseline_updated": security.get("baseline_updated"),
                }
                if security else None
            ),
            "security_audit": (
                {
                    "generated_at": security_audit.get("generated_at"),
                    "status": security_audit.get("status"),
                    "privacy_mode": security_audit.get("privacy_mode"),
                    "summary": security_audit.get("summary"),
                    "findings": security_audit.get("findings", []),
                }
                if security_audit else None
            ),
            "security_posture": (
                {
                    "generated_at": security_posture.get("generated_at"),
                    "status": security_posture.get("status"),
                    "privacy_mode": security_posture.get("privacy_mode"),
                    "summary": security_posture.get("summary"),
                    "findings": security_posture.get("findings", []),
                }
                if security_posture else None
            ),
            "acl_hardening": (
                {
                    "generated_at": acl_hardening.get("generated_at"),
                    "status": acl_hardening.get("status"),
                    "backup_available": bool(acl_hardening.get("backup_root")),
                    "summary": acl_hardening.get("summary"),
                }
                if acl_hardening else None
            )}


def _render_html(snapshot: dict[str, Any]) -> str:
    payload = json.dumps(snapshot, ensure_ascii=False).replace("</", "<\\/")
    generated = html.escape(snapshot["generated_at"])
    return f'''<!doctype html>
<html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Workspace 文件位置</title>
<style>
:root{{--bg:#f5f7fb;--panel:#fff;--text:#172033;--muted:#637083;--line:#dce2ec;--accent:#2864dc;--good:#18794e;--warn:#9a6700;--bad:#c9372c;--tag:#eef2f8}}
@media(prefers-color-scheme:dark){{:root{{--bg:#11151d;--panel:#181e28;--text:#eef2f7;--muted:#a7b1c0;--line:#303a49;--accent:#7aa2ff;--good:#53c28b;--warn:#e5b94d;--bad:#ff7b72;--tag:#252d39}}}}
*{{box-sizing:border-box}}body{{margin:0;background:var(--bg);color:var(--text);font:14px/1.55 system-ui,"Microsoft YaHei",sans-serif}}
main{{max-width:1200px;margin:auto;padding:24px}}h1{{font-size:24px;margin:0 0 4px}}.muted{{color:var(--muted)}}
.summary{{display:grid;grid-template-columns:repeat(auto-fit,minmax(145px,1fr));gap:10px;margin:20px 0}}.card{{background:var(--panel);border:1px solid var(--line);border-radius:10px;padding:14px}}.num{{font-size:25px;font-weight:600}}
.controls{{display:flex;gap:10px;flex-wrap:wrap;margin:14px 0}}input,select,button{{font:inherit;color:inherit;background:var(--panel);border:1px solid var(--line);border-radius:7px;padding:9px 11px}}input{{min-width:260px;flex:1}}button{{cursor:pointer}}button:hover{{border-color:var(--accent)}}
.table-wrap{{overflow:auto;background:var(--panel);border:1px solid var(--line);border-radius:10px}}table{{width:100%;border-collapse:collapse;min-width:850px}}th,td{{padding:10px 12px;border-bottom:1px solid var(--line);text-align:left;vertical-align:top}}th{{position:sticky;top:0;background:var(--panel)}}tr:last-child td{{border-bottom:0}}
.tag{{display:inline-block;background:var(--tag);border-radius:999px;padding:2px 8px;white-space:nowrap}}.BOTH_SAME{{color:var(--good)}}.CONFLICT{{color:var(--bad);font-weight:600}}.COMPUTER_ONLY,.NAS_ONLY,.BOTH_UNVERIFIED{{color:var(--warn)}}
.path{{max-width:430px;word-break:break-all}}a{{color:var(--accent)}}.actions{{display:flex;gap:6px;flex-wrap:wrap}}.empty{{padding:28px;text-align:center;color:var(--muted)}}
@media(max-width:600px){{main{{padding:14px}}input{{min-width:100%}}}}
</style></head><body><main>
<h1>Workspace 文件位置</h1><div class="muted">快照时间：{generated} · 只读目录，不会移动或删除文件</div>
<section class="summary" id="summary"></section>
<div class="controls"><input id="search" type="search" placeholder="搜索文件名或相对路径" aria-label="搜索文件"><select id="state" aria-label="位置状态"><option value="">全部位置</option><option value="COMPUTER_ONLY">仅电脑</option><option value="NAS_ONLY">仅 NAS</option><option value="BOTH_SAME">两边一致</option><option value="BOTH_UNVERIFIED">两边待核验</option><option value="CONFLICT">版本冲突</option></select><button id="reset" type="button">清除筛选</button></div>
<div class="table-wrap"><table><thead><tr><th>状态</th><th>文件</th><th>大小</th><th>电脑</th><th>NAS</th><th>操作</th></tr></thead><tbody id="rows"></tbody></table><div id="empty" class="empty" hidden>没有匹配文件</div></div>
<script id="snapshot-data" type="application/json">{payload}</script>
<script>
const DATA=JSON.parse(document.getElementById('snapshot-data').textContent);
const LABEL={{COMPUTER_ONLY:'仅电脑',NAS_ONLY:'仅 NAS',BOTH_SAME:'两边一致',BOTH_UNVERIFIED:'两边待核验',CONFLICT:'版本冲突'}};
const summary=document.getElementById('summary'),rows=document.getElementById('rows'),empty=document.getElementById('empty'),search=document.getElementById('search'),state=document.getElementById('state');
const esc=s=>String(s??'').replace(/[&<>"']/g,c=>({{'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}}[c]));
const size=n=>n<1024?n+' B':n<1048576?(n/1024).toFixed(1)+' KB':n<1073741824?(n/1048576).toFixed(1)+' MB':(n/1073741824).toFixed(2)+' GB';
summary.innerHTML=[['COMPUTER_ONLY','仅电脑'],['NAS_ONLY','仅 NAS'],['BOTH_SAME','两边一致'],['CONFLICT','冲突']].map(([k,l])=>`<div class="card"><div class="muted">${{l}}</div><div class="num ${{k}}">${{DATA.counts[k]||0}}</div></div>`).join('');
function button(path,label){{return path?`<button type="button" data-copy="${{esc(path)}}">${{label}}</button>`:''}}
function render(){{const q=search.value.trim().toLowerCase(),s=state.value;const list=DATA.files.filter(f=>(!s||f.state===s)&&(!q||(f.relative+' '+f.name).toLowerCase().includes(q)));rows.innerHTML=list.map(f=>`<tr><td><span class="tag ${{f.state}}">${{LABEL[f.state]}}</span><div class="muted">${{esc(f.reason)}}</div></td><td class="path"><strong>${{esc(f.name)}}</strong><div class="muted">${{esc(f.relative)}}</div></td><td>${{size(f.size)}}</td><td>${{f.computer?'有':'—'}}</td><td>${{f.nas?'有':'—'}}</td><td><div class="actions">${{f.computer_uri?`<a href="${{esc(f.computer_uri)}}">打开电脑位置</a>`:''}} ${{f.nas_uri?`<a href="${{esc(f.nas_uri)}}">打开 NAS 位置</a>`:''}} ${{button(f.computer?.path||f.nas?.path,'复制路径')}}</div></td></tr>`).join('');empty.hidden=list.length>0;}}
search.addEventListener('input',render);state.addEventListener('change',render);document.getElementById('reset').addEventListener('click',()=>{{search.value='';state.value='';render();}});rows.addEventListener('click',async e=>{{const b=e.target.closest('button[data-copy]');if(!b)return;await navigator.clipboard.writeText(b.dataset.copy);const old=b.textContent;b.textContent='已复制';setTimeout(()=>b.textContent=old,900);}});render();
</script></main></body></html>'''


def _render_dashboard_html(snapshot: dict[str, Any]) -> str:
    template_path = Path(__file__).resolve().parents[2] / "templates" / "location-dashboard.html"
    template = template_path.read_text(encoding="utf-8")
    payload = json.dumps(snapshot, ensure_ascii=False).replace("</", "<\\/")
    generated_at = datetime.fromisoformat(snapshot["generated_at"]).astimezone(timezone(timedelta(hours=8)))
    generated = html.escape(generated_at.date().isoformat())
    return (
        template.replace("__PAYLOAD__", payload)
        .replace("__GENERATED__", generated)
        .replace("__APP_VERSION__", html.escape(str(snapshot.get("app_version") or APP_VERSION)))
        .replace("__TEMPLATE_VERSION__", html.escape(str(snapshot.get("template_version") or TEMPLATE_VERSION)))
    )


def save_location_snapshot(snapshot: dict[str, Any], output: str | Path) -> tuple[Path, Path]:
    html_path = Path(output).resolve()
    json_path = html_path.with_suffix(".json")
    html_path.parent.mkdir(parents=True, exist_ok=True)
    for target, content in ((html_path, _render_dashboard_html(snapshot)), (json_path, json.dumps(snapshot, ensure_ascii=False, indent=2))):
        fd, temp_name = tempfile.mkstemp(prefix=target.name + ".", suffix=".tmp", dir=target.parent)
        try:
            with os.fdopen(fd, "w", encoding="utf-8", newline="") as handle:
                handle.write(content)
            os.replace(temp_name, target)
        except Exception:
            try: os.unlink(temp_name)
            except OSError: pass
            raise
    return html_path, json_path
