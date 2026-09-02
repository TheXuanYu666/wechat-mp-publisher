#!/usr/bin/env python3
"""选题查重 + 已写台账维护。规则：只写没写过的、最近比较火的跑鞋/篮球鞋。

热度由 agent 用 istarshine-trending-search / istarshine-domestic-web-wide-search / web_search
去搜（搜索服务不可用时退回 web_search），拿到候选后用本脚本过一遍查重。

用法:
  topic_pick.py list
  topic_pick.py check --name "Nike Pegasus 41"
  topic_pick.py filter --candidates "Nike Pegasus 41,飞燃3,Adizero Adios Pro 4,安踏马赫5"
  topic_pick.py add --name "Nike Pegasus 41" --column 跑鞋篇 --date 2026-08-30 --url https://mp.weixin.qq.com/s/xxx
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any

LEDGER = Path(__file__).resolve().parent.parent / "references" / "published.json"


def norm(s: str) -> str:
    """去掉空格、°、%、大小写差异，便于模糊比对。"""
    s = s.lower()
    s = re.sub(r"[\s\-_·°%’'\"()（）]", "", s)
    return s


def load() -> dict[str, Any]:
    return json.loads(LEDGER.read_text(encoding="utf-8"))


def save(data: dict[str, Any]) -> None:
    LEDGER.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def match(name: str, entry: dict[str, Any]) -> bool:
    n = norm(name)
    keys = [entry["name"]] + entry.get("aliases", [])
    for k in keys:
        nk = norm(k)
        if not nk:
            continue
        if n == nk or nk in n or n in nk:
            return True
    return False


def find(name: str, data: dict[str, Any]) -> dict[str, Any] | None:
    for e in data.get("written", []):
        if match(name, e):
            return e
    return None


def cmd_list(_args: argparse.Namespace) -> int:
    data = load()
    rows = [
        {
            "name": e["name"],
            "column": e.get("column"),
            "published": e.get("published"),
            "confirmed": e.get("confirmed", False),
        }
        for e in data.get("written", [])
    ]
    unconfirmed = [r["name"] for r in rows if not r["confirmed"]]
    print(json.dumps({"count": len(rows), "written": rows,
                      "need_user_confirm": unconfirmed}, ensure_ascii=False, indent=2))
    return 0


def cmd_check(args: argparse.Namespace) -> int:
    data = load()
    hit = find(args.name, data)
    print(json.dumps({
        "name": args.name,
        "written": hit is not None,
        "matched": hit["name"] if hit else None,
        "confirmed": hit.get("confirmed") if hit else None,
        "url": hit.get("url") if hit else None,
        "verdict": ("已写过，换一双" if hit and hit.get("confirmed")
                    else "台账里有但未确认发布，先问用户" if hit
                    else "没写过，可以写"),
    }, ensure_ascii=False, indent=2))
    return 0 if hit is None else 1


def cmd_filter(args: argparse.Namespace) -> int:
    data = load()
    cands = [c.strip() for c in args.candidates.split(",") if c.strip()]
    fresh, dup, unsure = [], [], []
    for c in cands:
        hit = find(c, data)
        if hit is None:
            fresh.append(c)
        elif hit.get("confirmed"):
            dup.append({"candidate": c, "matched": hit["name"], "url": hit.get("url")})
        else:
            unsure.append({"candidate": c, "matched": hit["name"], "note": hit.get("note")})
    print(json.dumps({"fresh": fresh, "already_written": dup, "need_user_confirm": unsure,
                      "next": "从 fresh 里按热度挑一双；unsure 里的先问用户发过没"},
                     ensure_ascii=False, indent=2))
    return 0


def cmd_add(args: argparse.Namespace) -> int:
    data = load()
    hit = find(args.name, data)
    if hit is not None and hit.get("confirmed"):
        print(json.dumps({"status": "already_present", "matched": hit["name"]},
                         ensure_ascii=False, indent=2))
        return 1
    entry = {
        "name": args.name,
        "aliases": [a.strip() for a in (args.aliases or "").split(",") if a.strip()],
        "column": args.column,
        "published": args.date,
        "url": args.url,
        "confirmed": True,
    }
    if hit is not None:
        data["written"][data["written"].index(hit)] = entry
        action = "updated"
    else:
        data["written"].append(entry)
        action = "added"
    save(data)
    print(json.dumps({"status": action, "entry": entry, "total": len(data["written"])},
                     ensure_ascii=False, indent=2))
    return 0


def cmd_confirm(args: argparse.Namespace) -> int:
    """用户确认某双到底发过没：--written yes/no"""
    data = load()
    hit = find(args.name, data)
    if hit is None:
        print(json.dumps({"status": "not_in_ledger", "name": args.name}, ensure_ascii=False, indent=2))
        return 1
    if args.written == "no":
        data["written"] = [e for e in data["written"] if e is not hit]
        save(data)
        print(json.dumps({"status": "removed", "name": hit["name"],
                          "note": "未发布，已从台账移除，可以写"}, ensure_ascii=False, indent=2))
        return 0
    hit["confirmed"] = True
    if args.date:
        hit["published"] = args.date
    if args.url:
        hit["url"] = args.url
    save(data)
    print(json.dumps({"status": "confirmed", "entry": hit}, ensure_ascii=False, indent=2))
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="选题查重与台账")
    sub = ap.add_subparsers(dest="cmd", required=True)

    sub.add_parser("list").set_defaults(func=cmd_list)

    c = sub.add_parser("check"); c.add_argument("--name", required=True); c.set_defaults(func=cmd_check)

    f = sub.add_parser("filter"); f.add_argument("--candidates", required=True)
    f.set_defaults(func=cmd_filter)

    a = sub.add_parser("add")
    a.add_argument("--name", required=True)
    a.add_argument("--column", required=True, choices=["跑鞋篇", "篮球鞋篇"])
    a.add_argument("--date", required=True)
    a.add_argument("--url")
    a.add_argument("--aliases")
    a.set_defaults(func=cmd_add)

    cf = sub.add_parser("confirm")
    cf.add_argument("--name", required=True)
    cf.add_argument("--written", required=True, choices=["yes", "no"])
    cf.add_argument("--date")
    cf.add_argument("--url")
    cf.set_defaults(func=cmd_confirm)

    args = ap.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
