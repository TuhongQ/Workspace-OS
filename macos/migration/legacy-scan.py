#!/usr/bin/env python3
from __future__ import annotations
import argparse, csv, sys
from pathlib import Path

PYTHON_TOOLS = Path(__file__).resolve().parents[1] / "scripts" / "python"
sys.path.insert(0, str(PYTHON_TOOLS))
from classifier import classify_file
from path_safety import iter_files_no_links
from version_detector import parse_version

def main() -> int:
    p = argparse.ArgumentParser(description="扫描旧文件并生成待人工确认的迁移清单")
    p.add_argument("source"); p.add_argument("--output", default="migration-plan.csv"); args = p.parse_args()
    root = Path(args.source).resolve()
    if not root.is_dir(): p.error(f"源目录不存在: {root}")
    fields = ["source","destination","size","sha256","suggested_category","version","status","duplicate_group","approved","notes"]
    with Path(args.output).open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields); writer.writeheader()
        for path in sorted(iter_files_no_links(root)):
            if not path.is_file(): continue
            suggestion, parsed = classify_file(path), parse_version(path)
            writer.writerow({"source": str(path), "destination": "", "size": path.stat().st_size, "sha256": "",
                "suggested_category": suggestion["suggested_target"], "version": parsed["version_text"] or "",
                "status": parsed["status"] or "", "duplicate_group": "", "approved": "no", "notes": suggestion["reason"]})
    print(f"已生成清单：{args.output}（未修改源文件）"); return 0

if __name__ == "__main__": raise SystemExit(main())
