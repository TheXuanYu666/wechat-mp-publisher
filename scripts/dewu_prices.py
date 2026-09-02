#!/usr/bin/env python3
"""得物（二级市场）配色价格清洗：把你报的配色价格算成可直接进文章的区间。

为什么不自动抓：核实过 dewu.com 桌面端只是 App 下载落地页——首页、搜索页、商品页三个
不同 URL 返回完全相同的页面，没有服务端商品数据，网页端拿不到价格。所以价格由你从得物 App
提供，脚本只负责清洗与剔除，数字反而更可靠。

输入格式随便写，一行一个配色，都能认：
    黑白 829
    全黑,845
    白蓝 ¥798
    某联名 4200元

用法:
  dewu_prices.py filter --text "黑白 829
  全黑 845" --out clean.json --shoe "飞燃3"
  dewu_prices.py filter --input prices.txt --out clean.json --shoe "飞燃3"
"""
from __future__ import annotations

import argparse
import csv
import json
import re
import statistics
import time
import sys
from pathlib import Path
from typing import Any

PROFILE_DIR = Path.home() / ".kiro" / "dewu-browser-profile"
CHROME = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"

# 这些词命中即视为联名/限定，直接省略
EXCLUDE_RX = re.compile(
    r"(联名|联乘|限定|限量|抽签|定制|复刻|纪念|艺术家|合作款|礼盒|套装|OFF-WHITE|Sacai|Travis|"
    r"Fragment|Union|Undefeated|Collab|Special\s*Box|SP\b)",
    re.IGNORECASE,
)
PRICE_KEYS = ("price", "minprice", "salePrice", "sale_price", "lowestPrice", "showPrice")
NAME_KEYS = ("title", "name", "propertyValue", "properties", "skuName", "colorName", "subTitle")


# ----------------------------------------------------------------- filter
def normalize_price(v: float) -> float:
    """得物接口常用分为单位；>20000 视为分。"""
    return round(v / 100, 2) if v >= 20000 else float(v)


LINE_RX = re.compile(r"^\s*(?P<name>.+?)[\s,，:：]+[¥￥]?\s*(?P<price>\d+(?:\.\d+)?)\s*元?\s*(?P<url>https?://\S+)?\s*$")


def parse_text(text: str) -> list[dict[str, Any]]:
    """一行一个配色，宽松解析。解析不了的行会被报告出来。"""
    items: list[dict[str, Any]] = []
    bad: list[str] = []
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        m = LINE_RX.match(line)
        if not m:
            bad.append(line)
            continue
        items.append({
            "name": m.group("name").strip(" ,，:："),
            "raw_price": float(m.group("price")),
            "url": m.group("url") or "",
        })
    if bad:
        print(json.dumps({"unparsed_lines": bad}, ensure_ascii=False), file=sys.stderr)
    return items


def load_items(path: Path) -> list[dict[str, Any]]:
    if path.suffix.lower() in (".txt", ".md"):
        return parse_text(path.read_text(encoding="utf-8"))
    if path.suffix.lower() == ".csv":
        items = []
        with path.open(encoding="utf-8-sig") as f:
            for row in csv.reader(f):
                if len(row) < 2 or not row[1].strip():
                    continue
                try:
                    price = float(row[1].replace(",", "").replace("元", "").strip())
                except ValueError:
                    continue
                items.append({"name": row[0].strip(), "raw_price": price,
                              "url": row[2].strip() if len(row) > 2 else ""})
        return items
    data = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(data, dict):
        return data.get("candidates") or data.get("items") or []
    return data


def filter_prices(items: list[dict], *, hi: float, lo: float, min_price: float) -> dict[str, Any]:
    rows = []
    for it in items:
        name = str(it.get("name", "")).strip()
        raw = it.get("raw_price", it.get("price"))
        if name.startswith("__error__") or raw in (None, "", -1):
            continue
        price = normalize_price(float(raw))
        if price < min_price:
            continue
        rows.append({"colorway": name, "price": price, "url": it.get("url", "")})

    # 同配色取最低价
    best: dict[str, dict] = {}
    for r in rows:
        k = r["colorway"]
        if k not in best or r["price"] < best[k]["price"]:
            best[k] = r
    rows = sorted(best.values(), key=lambda r: r["price"])

    dropped: list[dict] = []
    kept = []
    for r in rows:
        if EXCLUDE_RX.search(r["colorway"]):
            dropped.append({**r, "reason": "联名/限定关键词"})
        else:
            kept.append(r)

    if not kept:
        return {"status": "no_data", "kept": [], "dropped": dropped, "stats": {}}

    med = statistics.median(p["price"] for p in kept)
    final, outliers = [], []
    for r in kept:
        if r["price"] > med * hi:
            outliers.append({**r, "reason": f"高于中位价 {med} 的 {hi} 倍"})
        elif r["price"] < med * lo:
            outliers.append({**r, "reason": f"低于中位价 {med} 的 {lo} 倍"})
        else:
            final.append(r)
    dropped += outliers

    prices = [r["price"] for r in final]
    return {
        "status": "ok",
        "kept": final,
        "dropped": dropped,
        "stats": {
            "count": len(final),
            "median": statistics.median(prices) if prices else None,
            "min": min(prices) if prices else None,
            "max": max(prices) if prices else None,
            "mainstream_range": f"{int(min(prices))}–{int(max(prices))} 元" if prices else None,
        },
    }


def cmd_filter(args: argparse.Namespace) -> int:
    if args.text:
        items = parse_text(args.text)
        src = "--text"
    else:
        path = Path(args.input).expanduser()
        items = load_items(path)
        src = str(path)
    if not items:
        print(json.dumps({"status": "no_input",
                          "hint": "一行一个配色，例如：黑白 829"}, ensure_ascii=False, indent=2))
        return 2
    res = filter_prices(items, hi=args.high_mult, lo=args.low_mult, min_price=args.min_price)
    res["shoe"] = args.shoe
    res["source"] = src
    out = Path(args.out).expanduser()
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(res, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"status": res["status"], "kept": len(res["kept"]),
                      "dropped": len(res["dropped"]), "stats": res["stats"], "out": str(out)},
                     ensure_ascii=False, indent=2))
    return 0 if res["status"] == "ok" else 7


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="得物二级市场价格清洗")
    sub = ap.add_subparsers(dest="cmd", required=True)

    f = sub.add_parser("filter", help="清洗 + 离群剔除")
    g = f.add_mutually_exclusive_group(required=True)
    g.add_argument("--input", help="txt / csv / json 文件")
    g.add_argument("--text", help="直接传入多行文本，一行一个「配色 价格」")
    f.add_argument("--out", required=True)
    f.add_argument("--shoe", default="")
    f.add_argument("--high-mult", type=float, default=1.8, help="高于中位价该倍数即省略")
    f.add_argument("--low-mult", type=float, default=0.55, help="低于中位价该倍数即省略")
    f.add_argument("--min-price", type=float, default=100)
    f.set_defaults(func=cmd_filter)

    args = ap.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
