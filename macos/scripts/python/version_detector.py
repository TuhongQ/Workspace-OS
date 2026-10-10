"""从文件名和路径识别版本，并选择正式版、工作版和审核版。"""
from __future__ import annotations

import re
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable

from path_safety import is_link_or_reparse, iter_files_no_links

VERSION_RE = re.compile(r"(?<![A-Za-z0-9])v(\d+)(?:\.(\d+))?(?:\.(\d+))?(?![A-Za-z0-9])", re.I)
DATE_RE = re.compile(r"(?<!\d)(20\d{2})[-_]?([01]\d)[-_]?([0-3]\d)(?!\d)")
STATUS_RE = re.compile(r"(?:^|[_\-.])(RELEASE|APPROVED|REVIEW|DRAFT|ARCHIVE)(?:[_\-.]|$)", re.I)
EXCLUDED = {"tmp", "temp", "cache", "caches", "proxy", "proxies", "render-cache"}


def parse_version(path: str | Path) -> dict[str, Any]:
    p = Path(path)
    text = p.name
    match = VERSION_RE.search(text)
    date_match = DATE_RE.search(text)
    status_match = STATUS_RE.search(text)
    version = tuple(int(x or 0) for x in match.groups()) if match else (0, 0, 0)
    date = "-".join(date_match.groups()) if date_match else None
    status = status_match.group(1).upper() if status_match else None
    lowered_parts = {part.lower() for part in p.parts}
    excluded = bool(lowered_parts & EXCLUDED) or text.startswith(("~$", "."))
    return {"path": str(p), "version": version, "version_text": match.group(0) if match else None,
            "date": date, "status": status, "in_release": "release" in lowered_parts, "excluded": excluded}


def _score(item: dict[str, Any], mtime: float = 0.0) -> tuple[Any, ...]:
    status_rank = {"RELEASE": 5, "APPROVED": 4, "REVIEW": 3, "DRAFT": 2, "ARCHIVE": 1, None: 0}
    date_num = int((item["date"] or "0000-00-00").replace("-", ""))
    return (0 if item["excluded"] else 1, status_rank[item["status"]], item["version"],
            date_num, 1 if item["in_release"] else 0, mtime)


def detect_latest(paths: Iterable[str | Path]) -> dict[str, Any]:
    candidates = []
    for raw in paths:
        p = Path(raw)
        info = parse_version(p)
        try:
            mtime = p.stat().st_mtime
        except OSError:
            mtime = 0.0
        info["mtime"] = mtime
        info["score"] = _score(info, mtime)
        candidates.append(info)
    usable = [x for x in candidates if not x["excluded"]]
    formal = [x for x in usable if x["status"] in {"RELEASE", "APPROVED"} or x["in_release"]]
    review = [x for x in usable if x["status"] == "REVIEW"]
    working = [x for x in usable if x["status"] not in {"RELEASE", "APPROVED", "ARCHIVE"}]
    pick = lambda xs: max(xs, key=lambda x: x["score"], default=None)
    conflicts = []
    if formal:
        top = pick(formal)
        conflicts = [x for x in formal if x is not top and x["version"] == top["version"]]
    return {"formal_latest": pick(formal), "working_latest": pick(working), "review_latest": pick(review),
            "possible_conflicts": conflicts, "candidate_count": len(candidates),
            "reason": "正式版优先，其次比较版本号、日期、release 路径和修改时间；临时/缓存/代理文件已排除。"}


def scan_latest(root: str | Path) -> dict[str, Any]:
    base = Path(root)
    if base.is_file():
        siblings = [
            p for p in base.parent.iterdir()
            if p.is_file() and not is_link_or_reparse(p)
        ]
    else:
        siblings = list(iter_files_no_links(base))
    return detect_latest(siblings)
