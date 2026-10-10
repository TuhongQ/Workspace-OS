#!/usr/bin/env python3
from __future__ import annotations
import argparse, json, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts" / "python"))
from index_builder import search_index
p=argparse.ArgumentParser(description="搜索 Workspace JSON 索引"); p.add_argument("index"); p.add_argument("query", nargs="?", default="")
for key in ("project","status","extension","version","category","archive_state"): p.add_argument(f"--{key.replace('_','-')}")
for key in ("date_from", "date_to"): p.add_argument(f"--{key.replace('_','-')}", help="YYYY-MM-DD")
p.add_argument("--released-only", action="store_true", help="只搜索正式发布/批准版本")
a=p.parse_args(); data=json.loads(Path(a.index).read_text(encoding="utf-8")); filters={k:v for k,v in vars(a).items() if k not in {"index","query"} and v is not None}
print(json.dumps(search_index(data, a.query, **filters), ensure_ascii=False, indent=2))
