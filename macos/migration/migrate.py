#!/usr/bin/env python3
from __future__ import annotations
import argparse, csv, json, shutil, sys
from datetime import datetime, timezone
from pathlib import Path

PYTHON_TOOLS = Path(__file__).resolve().parents[1] / "scripts" / "python"
sys.path.insert(0, str(PYTHON_TOOLS))
from duplicate_finder import sha256_file

def main() -> int:
    p = argparse.ArgumentParser(description="按审核清单安全复制旧文件")
    p.add_argument("plan"); p.add_argument("--workspace", required=True); p.add_argument("--apply", action="store_true")
    p.add_argument("--move", action="store_true", help="高风险：移动而非复制；仍不删除")
    args = p.parse_args(); workspace = Path(args.workspace).resolve()
    operations = []
    with Path(args.plan).open(encoding="utf-8-sig", newline="") as handle:
        for row in csv.DictReader(handle):
            if row.get("approved", "").lower() not in {"yes","true","1"} or not row.get("destination"): continue
            src = Path(row["source"]).resolve(); dst = (workspace / row["destination"]).resolve()
            try: dst.relative_to(workspace)
            except ValueError: raise SystemExit(f"目标越出 Workspace: {dst}")
            item = {"source": str(src), "destination": str(dst), "mode": "move" if args.move else "copy", "status": "planned"}
            operations.append(item)
            if not args.apply: continue
            if not src.is_file(): item["status"] = "missing"; continue
            if dst.exists(): item["status"] = "skipped-existing"; continue
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(src), str(dst)) if args.move else shutil.copy2(src, dst)
            item["sha256"] = sha256_file(dst)
            if not args.move and item["sha256"] != sha256_file(src): raise IOError(f"复制校验失败: {src}")
            item["status"] = "completed"
    record = {"schema_version":"1.0", "created_at":datetime.now(timezone.utc).isoformat(), "applied":args.apply,
              "operations":operations, "rollback_note":"移动模式按 from/to 反向移动；复制模式将目标移入 Quarantine。脚本不自动删除。"}
    out = workspace / "07_Admin" / "WorkspaceOS" / "logs" / f"migration-{datetime.now().strftime('%Y%m%d-%H%M%S')}.json"
    if args.apply: out.parent.mkdir(parents=True, exist_ok=True); out.write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(record, ensure_ascii=False, indent=2)); return 0

if __name__ == "__main__": raise SystemExit(main())

