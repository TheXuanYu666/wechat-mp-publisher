#!/usr/bin/env python3
"""从公开合集页自动同步「已发文章」台账，不需要后台登录。

原理：公众号文章页里带 `__biz` 和所属合集 `album_id`，而合集接口
`mp.weixin.qq.com/mp/appmsgalbum?action=getalbum&__biz=..&album_id=..&f=json`
是公开可读的，能列出该合集下全部文章的标题、链接、发布时间。

用法:
  fetch_published.py --from-article https://mp.weixin.qq.com/s/xxx --from-article https://mp.weixin.qq.com/s/yyy
  fetch_published.py --biz <你的 __biz> --album <合集1 id> --album <合集2 id>
  fetch_published.py --from-article <url> --write        # 直接写入 references/published.json
"""
from __future__ import annotations

import argparse
import datetime
import json
import re
import sys
from pathlib import Path
from typing import Any

import requests

sys.path.insert(0, str(Path(__file__).parent))
from learn_style import fetch  # noqa: E402

LEDGER = Path(__file__).resolve().parent.parent / "references" / "published.json"
UA_MOB = (
    "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15 "
    "(KHTML, like Gecko) Version/17.0 Mobile/15E148 Safari/604.1"
)
ALBUM_API = "https://mp.weixin.qq.com/mp/appmsgalbum"


def discover(article_url: str) -> tuple[str, list[str]]:
    html = fetch(article_url)
    biz = ""
    m = re.search(r'var biz = "([^"]+)"', html) or re.search(r"__biz=([\w=+/]+)", html)
    if m:
        biz = m.group(1)
    ids = set(re.findall(r"album_id:\s*'(\d+)'", html)) | set(re.findall(r"album_id=(\d+)", html))
    return biz, sorted(ids)


def get_album(biz: str, album_id: str, *, timeout: int = 30) -> list[dict[str, Any]]:
    """拉一个合集的全部文章，翻页直到 continue_flag 为 0。"""
    out: list[dict[str, Any]] = []
    begin = ""
    for _ in range(20):
        params = {
            "action": "getalbum",
            "__biz": biz,
            "album_id": album_id,
            "count": "30",
            "f": "json",
        }
        if begin:
            params["begin_msgid"] = begin
        r = requests.get(ALBUM_API, params=params, headers={"User-Agent": UA_MOB}, timeout=timeout)
        r.raise_for_status()
        data = r.json().get("getalbum_resp", {})
        arts = data.get("article_list", []) or []
        if not arts:
            break
        out += arts
        if str(data.get("continue_flag", "0")) not in ("1", "true"):
            break
        begin = arts[-1].get("msgid", "")
        if not begin:
            break
    # 按 msgid 去重
    seen, uniq = set(), []
    for a in out:
        k = (a.get("msgid"), a.get("itemidx"))
        if k in seen:
            continue
        seen.add(k)
        uniq.append(a)
    return uniq


def normalize_url(u: str) -> str:
    return (u or "").replace("http://", "https://").replace("&amp;", "&")


def to_entry(a: dict[str, Any]) -> dict[str, Any]:
    title = a.get("title", "").strip()
    column, _, shoe = title.partition("——")
    shoe = shoe.strip() or title
    ts = int(a.get("create_time", 0) or 0)
    aliases = {shoe.replace(" ", ""), shoe.replace("°", ""), re.sub(r"[^\w]", "", shoe)}
    aliases.discard(shoe)
    return {
        "name": shoe,
        "aliases": sorted(x for x in aliases if x),
        "column": column.strip() or None,
        "published": str(datetime.date.fromtimestamp(ts)) if ts else None,
        "url": normalize_url(a.get("url", "")),
        "title": title,
        "confirmed": True,
    }


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="同步已发文章台账")
    ap.add_argument("--from-article", action="append", default=[], help="任意一篇文章链接，用于发现 biz 和合集")
    ap.add_argument("--biz")
    ap.add_argument("--album", action="append", default=[])
    ap.add_argument("--write", action="store_true", help="写入 references/published.json")
    args = ap.parse_args(argv)

    biz = args.biz or ""
    albums: set[str] = set(args.album)
    errors: list[str] = []
    for u in args.from_article:
        try:
            b, ids = discover(u)
            biz = biz or b
            albums |= set(ids)
        except Exception as exc:  # noqa: BLE001
            errors.append(f"{u}: {exc}")

    if not biz or not albums:
        print(json.dumps({"status": "insufficient", "biz": biz, "albums": sorted(albums),
                          "errors": errors,
                          "hint": "至少给一篇属于合集的文章链接，或直接传 --biz 与 --album"},
                         ensure_ascii=False, indent=2))
        return 2

    entries: list[dict[str, Any]] = []
    per_album = []
    for aid in sorted(albums):
        try:
            arts = get_album(biz, aid)
        except Exception as exc:  # noqa: BLE001
            errors.append(f"album {aid}: {exc}")
            continue
        per_album.append({"album_id": aid, "articles": len(arts)})
        entries += [to_entry(a) for a in arts]

    # 同名合并，保留最早发布日期
    merged: dict[str, dict[str, Any]] = {}
    for e in entries:
        k = re.sub(r"[^\w]", "", e["name"]).lower()
        if k in merged and (merged[k].get("published") or "9999") <= (e.get("published") or "9999"):
            continue
        merged[k] = e
    final = sorted(merged.values(), key=lambda e: e.get("published") or "")

    payload = {
        "status": "ok" if final else "empty",
        "biz": biz,
        "albums": per_album,
        "count": len(final),
        "written": final,
        "errors": errors,
    }
    if args.write:
        ledger = {
            "_note": "已发文章台账，由 fetch_published.py 从公开合集页自动同步。"
                     "选题前用 topic_pick.py check/filter 查重，发完新草稿后 add。",
            "biz": biz,
            "albums": sorted(albums),
            "synced_at": datetime.datetime.now().strftime("%Y-%m-%d %H:%M"),
            "written": final,
        }
        LEDGER.write_text(json.dumps(ledger, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        payload["ledger"] = str(LEDGER)

    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0 if final else 7


if __name__ == "__main__":
    sys.exit(main())
