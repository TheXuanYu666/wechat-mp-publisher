#!/usr/bin/env python3
"""得物 App 截图识价：截图进 → 配色价格区间出。你只需要截图，不用手打。

得物网页端没有商品数据（桌面站是 App 下载页，商品接口返回 485 风控码），所以走截图路线：
在得物 App 里把配色/价格列表截下来 → 本机 Vision 离线 OCR → 配对「配色 + ¥价格」→
沿用 dewu_prices 的剔除规则 → 输出可直接填进「二级平台价格」的区间。

全程离线，不联网、不需要 API key、不碰你的账号。

用法:
  dewu_ocr.py --image s1.png --image s2.png --shoe "飞燃3" --out tmp/dewu_clean.json
  dewu_ocr.py --dir ~/Desktop/dewu截图 --shoe "飞燃3" --out tmp/dewu_clean.json --dump tmp/ocr.json
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).parent))
from dewu_prices import filter_prices  # noqa: E402

SWIFT = Path(__file__).parent / "ocr_text.swift"
IMG_EXT = {".png", ".jpg", ".jpeg", ".heic", ".webp"}

PRICE_RX = re.compile(r"^[¥￥]\s*(\d{2,5})(?:\.\d+)?$")
PRICE_INLINE_RX = re.compile(r"[¥￥]\s*(\d{2,5})(?:\.\d+)?")
# 明显不是配色名的行
NOISE_RX = re.compile(
    r"(得物|搜索|全部|筛选|排序|销量|上新|价格|收藏|分享|立即|购买|求购|出售|尺码|码数|"
    r"包邮|优惠|券|已鉴别|正品|查看|更多|评价|条评论|万人|人气|新品|活动|返回|首页|"
    r"^\d+$|^[¥￥]|^\d+%$|^US|^EU|^UK)"
)


def ocr(paths: list[Path]) -> list[dict[str, Any]]:
    if not SWIFT.exists():
        raise RuntimeError(f"找不到 OCR helper: {SWIFT}")
    cmd = ["swift", str(SWIFT)] + [str(p) for p in paths]
    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=600)
    if proc.returncode != 0:
        raise RuntimeError(f"OCR 失败: {proc.stderr[-400:]}")
    tail = proc.stdout.strip().splitlines()
    if not tail:
        raise RuntimeError("OCR 无输出")
    return json.loads(tail[-1])


def looks_like_colorway(text: str) -> bool:
    t = text.strip()
    if len(t) < 2 or len(t) > 40:
        return False
    if PRICE_RX.match(t) or NOISE_RX.search(t):
        return False
    return bool(re.search(r"[\u4e00-\u9fff A-Za-z]", t))


def pair_prices(page: dict[str, Any], max_dy: float = 0.08) -> list[dict[str, Any]]:
    """把每个价格和它最近的候选配色名配对：先看同一行左侧，再看上方最近一行。"""
    lines = page.get("lines", [])
    items: list[dict[str, Any]] = []
    for i, ln in enumerate(lines):
        m = PRICE_RX.match(ln["text"].strip()) or PRICE_INLINE_RX.search(ln["text"])
        if not m:
            continue
        price = float(m.group(1))
        # 价格与配色写在同一行：¥829 黑白
        same = PRICE_INLINE_RX.sub(" ", ln["text"]).strip(" ·-—|")
        if looks_like_colorway(same):
            items.append({"name": same, "raw_price": price, "_src": "same_line"})
            continue
        # 同一行内的其它文本块（y 接近）
        cands = [
            o
            for o in lines
            if o is not ln
            and abs(o["y"] - ln["y"]) < 0.015
            and looks_like_colorway(o["text"])
        ]
        if cands:
            best = min(cands, key=lambda o: abs(o["x"] - ln["x"]))
            items.append({"name": best["text"].strip(), "raw_price": price, "_src": "row"})
            continue
        # 往上找最近的候选名
        above = [
            o
            for o in lines[:i]
            if ln["y"] - o["y"] > 0
            and ln["y"] - o["y"] < max_dy
            and looks_like_colorway(o["text"])
        ]
        if above:
            best = min(above, key=lambda o: ln["y"] - o["y"])
            items.append({"name": best["text"].strip(), "raw_price": price, "_src": "above"})
            continue
        items.append({"name": f"未识别配色@{Path(page.get('path','')).name}", "raw_price": price,
                      "_src": "orphan"})
    return items


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="得物截图识价")
    ap.add_argument("--image", action="append", default=[])
    ap.add_argument("--dir", help="截图目录，自动取里面所有图片")
    ap.add_argument("--shoe", default="")
    ap.add_argument("--out", required=True)
    ap.add_argument("--dump", help="把 OCR 原始结果也存下来，便于核对")
    ap.add_argument("--high-mult", type=float, default=1.8)
    ap.add_argument("--low-mult", type=float, default=0.55)
    ap.add_argument("--min-price", type=float, default=100)
    args = ap.parse_args(argv)

    paths = [Path(p).expanduser() for p in args.image]
    if args.dir:
        d = Path(args.dir).expanduser()
        paths += sorted(p for p in d.iterdir() if p.suffix.lower() in IMG_EXT and not p.name.startswith("._"))
    paths = [p for p in paths if p.exists()]
    if not paths:
        print(json.dumps({"status": "no_input", "hint": "用 --image 或 --dir 指定截图"},
                         ensure_ascii=False, indent=2))
        return 2

    try:
        pages = ocr(paths)
    except Exception as exc:  # noqa: BLE001
        print(json.dumps({"status": "ocr_failed", "error": str(exc)[:300]}, ensure_ascii=False, indent=2))
        return 6

    if args.dump:
        Path(args.dump).expanduser().write_text(
            json.dumps(pages, ensure_ascii=False, indent=2), encoding="utf-8")

    items: list[dict[str, Any]] = []
    per_page = []
    for pg in pages:
        got = pair_prices(pg)
        per_page.append({"image": Path(pg.get("path", "")).name,
                         "lines": len(pg.get("lines", [])), "prices_found": len(got),
                         "error": pg.get("error")})
        items += got

    res = filter_prices(items, hi=args.high_mult, lo=args.low_mult, min_price=args.min_price)
    res["shoe"] = args.shoe
    res["source"] = "ocr"
    res["pages"] = per_page
    res["orphans"] = [i["name"] for i in items if i.get("_src") == "orphan"]

    out = Path(args.out).expanduser()
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(res, ensure_ascii=False, indent=2), encoding="utf-8")

    print(json.dumps({
        "status": res["status"], "pages": per_page,
        "kept": [(k["colorway"], k["price"]) for k in res["kept"]],
        "dropped": [(d["colorway"], d["price"], d["reason"]) for d in res["dropped"]],
        "stats": res["stats"],
        "note": "识别结果必须和截图核对一遍再进文章",
        "out": str(out),
    }, ensure_ascii=False, indent=2))
    return 0 if res["status"] == "ok" else 7


if __name__ == "__main__":
    sys.exit(main())
