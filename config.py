"""读取账号配置。没有 config.json 时回落到 config.example.json，方便别人克隆后直接跑。"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent


def load() -> dict[str, Any]:
    for name in ("config.json", "config.example.json"):
        f = ROOT / name
        if f.exists():
            return json.loads(f.read_text(encoding="utf-8"))
    return {}


CFG = load()


def assets_root() -> Path:
    return Path(CFG.get("assets_root", "/Volumes/YOUR_DISK/YOUR_FOLDER"))


def album_for(column: str) -> str:
    cols = CFG.get("columns", {})
    if column in cols:
        return cols[column].get("album", "")
    return "球鞋" if ("篮球" in column or "球鞋" in column) else "跑鞋"


def footer_defaults() -> dict[str, str]:
    return CFG.get("footer", {"tester": "", "editor": "", "reviewers": ""})
