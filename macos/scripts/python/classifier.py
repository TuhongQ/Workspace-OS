"""安全的两层文件分类：本地规则优先，可选 AI Provider。"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Any


class AIClassifierProvider:
    def classify(self, metadata: dict[str, Any], text_preview: str | None = None) -> dict[str, Any]:
        raise NotImplementedError


class MockAIProvider(AIClassifierProvider):
    def classify(self, metadata: dict[str, Any], text_preview: str | None = None) -> dict[str, Any]:
        return {"category": "00_Inbox/ToSort", "confidence": 0.25, "reason": "Mock Provider 未作外部调用"}


EXTENSION_TARGETS = {
    ".mp4": "03_Assets/Video", ".mov": "03_Assets/Video", ".mkv": "03_Assets/Video",
    ".jpg": "03_Assets/Images", ".jpeg": "03_Assets/Images", ".png": "03_Assets/Images",
    ".wav": "03_Assets/Audio", ".mp3": "03_Assets/Audio",
    ".py": "00_Inbox/ToSort", ".js": "00_Inbox/ToSort", ".cpp": "00_Inbox/ToSort",
    ".md": "02_Knowledge/Notes", ".pdf": "02_Knowledge/Notes",
    ".zip": "06_Release/Packages", ".dmg": "06_Release/Installers", ".exe": "06_Release/Installers",
}


def classify_file(path: str | Path, rules: dict[str, Any] | None = None,
                  provider: AIClassifierProvider | None = None, privacy_mode: str = "metadata-only") -> dict[str, Any]:
    p = Path(path)
    stat = p.stat()
    metadata = {"name": p.name, "extension": p.suffix.lower(), "size": stat.st_size,
                "modified_time": stat.st_mtime, "path": str(p)}
    target = EXTENSION_TARGETS.get(p.suffix.lower(), "00_Inbox/ToSort")
    confidence = 0.65 if target != "00_Inbox/ToSort" else 0.2
    reasons = [f"扩展名为 {p.suffix.lower() or '无'}"]
    for rule in (rules or {}).get("rules", []):
        keyword = str(rule.get("keyword", ""))
        if keyword and re.search(re.escape(keyword), p.name, re.I):
            target, confidence = rule["target"], float(rule.get("confidence", 0.85))
            reasons.append(f"文件名匹配关键词 {keyword}")
            break
    result = {"source": str(p), "suggested_target": target, "suggested_name": p.name,
              "confidence": confidence, "reason": "；".join(reasons), "privacy_mode": privacy_mode}
    if provider and confidence < 0.6:
        if privacy_mode not in {"metadata-only", "local-only", "content-preview", "full-content"}:
            raise ValueError("无效隐私模式")
        # 默认只发送元数据；本地 Provider 可由调用方自行读取内容。
        ai = provider.classify(metadata, None)
        result["ai_suggestion"] = ai
    return result
