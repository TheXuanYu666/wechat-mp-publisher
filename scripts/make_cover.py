#!/usr/bin/env python3
"""按步界社封面模板自动生成封面图。

模板来自两个 PSD（画布均 2350×1000）：
  · 英文名：Herculanum 字体
  · 含中文：中文用 STXingkaiSC-Light（华文行楷），英文部分仍用 Herculanum
构成：左侧社标（位置与尺寸照模板不变）+ 右侧鞋名 + 右下鞋的侧视图（去纯白背景）
鞋名与鞋图整体居中于社标右侧的空白区域。

用法:
  make_cover.py --shoe "Nike Pegasus 42" --side-view 官图/01_侧面.png --out 封面.png
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

CANVAS = (2350, 1000)
import sys as _s; _s.path.insert(0, str(Path(__file__).resolve().parent.parent))
from config import CFG as _C  # noqa: E402

LOGO = Path(_C.get("cover", {}).get("logo", ""))
LOGO_BOX = (0, 0, 1000, 1000)          # 照模板，位置尺寸不动
FONT_EN = "/Library/Fonts/Herculanum.ttf"
FONT_EN_ALT = "/System/Library/Fonts/Supplemental/Herculanum.ttf"
# 华文行楷在系统按需下载的字体库里，路径带哈希，用 glob 找
FONT_CN_GLOB = "/System/Library/AssetsV2/com_apple_MobileAsset_Font*/*/AssetData/Xingkai.ttc"
FONT_CN = '/System/Library/AssetsV2/com_apple_MobileAsset_Font8/13b8ce423f920875b28b551f9406bf1014e0a656.asset/AssetData/Xingkai.ttc' if True else ""
FONT_CN_ALT = "/System/Library/Fonts/Supplemental/Xingkai.ttc"
CJK_RX = re.compile(r"[\u4e00-\u9fff°]")


def pick(*paths: str) -> str | None:
    import glob as _g

    for p in paths:
        if not p:
            continue
        if Path(p).exists():
            return p
    for m in _g.glob(FONT_CN_GLOB):
        return m
    return None


def load_font(path: str | None, size: int, want: tuple[str, str] | None = None):
    """want=(family, style) 时在 .ttc 里挑指定字面。
    Xingkai.ttc 有 SC/TC × Bold/Light 四个面，PSD 用的是 STXingkaiSC-Light，
    默认 index=0 会取到 SC Bold，必须显式挑。
    """
    if not path:
        return ImageFont.load_default()
    if want:
        for i in range(8):
            try:
                f = ImageFont.truetype(path, size, index=i)
            except Exception:  # noqa: BLE001
                break
            if f.getname() == want:
                return f
    try:
        return ImageFont.truetype(path, size)
    except Exception:  # noqa: BLE001
        return ImageFont.load_default()


def trim_bg(img: Image.Image, tol: int = 26) -> Image.Image:
    """去掉背景只留鞋本身。背景色按四角采样判断，不假设一定是纯白
    （飞燃3 的侧视图就是灰底）。用洪水填充从边缘往里去，避免误伤鞋身内部的浅色。
    """
    from PIL import ImageDraw as _D

    img = img.convert("RGB")
    w, h = img.size
    corners = [img.getpixel(p) for p in ((0, 0), (w - 1, 0), (0, h - 1), (w - 1, h - 1))]
    bg = tuple(sum(c[i] for c in corners) // 4 for i in range(3))

    # 用 mask 记录背景：从四边洪水填充
    rgba = img.convert("RGBA")
    mask = Image.new("L", (w, h), 0)
    flood = img.copy()
    for seed in ((0, 0), (w - 1, 0), (0, h - 1), (w - 1, h - 1),
                 (w // 2, 0), (w // 2, h - 1), (0, h // 2), (w - 1, h // 2)):
        try:
            _D.floodfill(flood, seed, (255, 0, 255), thresh=tol)
        except Exception:  # noqa: BLE001
            pass
    px_f, px_m = flood.load(), mask.load()
    for y in range(h):
        for x in range(w):
            if px_f[x, y] == (255, 0, 255):
                px_m[x, y] = 255
    rgba.putalpha(Image.eval(mask, lambda v: 255 - v))
    bbox = rgba.getbbox()
    return rgba.crop(bbox) if bbox else rgba


def split_runs(text: str) -> list[tuple[str, bool]]:
    """把鞋名切成 (片段, 是否中文) 序列，中英分别用不同字体。"""
    runs: list[tuple[str, bool]] = []
    for ch in text:
        cjk = bool(CJK_RX.match(ch))
        if runs and runs[-1][1] == cjk:
            runs[-1] = (runs[-1][0] + ch, cjk)
        else:
            runs.append((ch, cjk))
    return runs


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="生成公众号封面")
    ap.add_argument("--shoe", required=True)
    ap.add_argument("--side-view", required=True, help="鞋的侧视图（会自动去白底）")
    ap.add_argument("--out", required=True)
    ap.add_argument("--color", default="#884b3f", help="鞋名文字颜色")
    ap.add_argument("--shoe-height", type=float, default=0.62,
                    help="鞋图高度占画布比例")
    args = ap.parse_args(argv)

    canvas = Image.new("RGBA", CANVAS, (255, 255, 255, 255))

    if LOGO.exists():
        logo = Image.open(LOGO).convert("RGBA")
        lw, lh = LOGO_BOX[2] - LOGO_BOX[0], LOGO_BOX[3] - LOGO_BOX[1]
        logo = logo.resize((lw, lh), Image.LANCZOS)
        canvas.alpha_composite(logo, (LOGO_BOX[0], LOGO_BOX[1]))

    # 社标右侧的可用区域
    area_x0, area_x1 = LOGO_BOX[2], CANVAS[0]
    area_w = area_x1 - area_x0

    sv = Path(args.side_view).expanduser()
    if not sv.exists():
        print(json.dumps({"status": "no_side_view", "path": str(sv)}, ensure_ascii=False))
        return 2
    shoe = trim_bg(Image.open(sv))
    target_h = int(CANVAS[1] * args.shoe_height)
    ratio = target_h / shoe.height
    shoe = shoe.resize((max(1, int(shoe.width * ratio)), target_h), Image.LANCZOS)
    if shoe.width > area_w * 0.92:                     # 太宽就按宽度收
        r2 = (area_w * 0.92) / shoe.width
        shoe = shoe.resize((int(shoe.width * r2), int(shoe.height * r2)), Image.LANCZOS)

    runs = split_runs(args.shoe)
    has_cjk = any(c for _, c in runs)
    size = 125 if has_cjk else 100
    f_en = load_font(pick(FONT_EN, FONT_EN_ALT), size, ("Herculanum", "Regular"))
    f_cn = load_font(pick(FONT_CN, FONT_CN_ALT), size, ("Xingkai SC", "Light"))

    c = args.color.lstrip("#")
    color = tuple(int(c[i:i + 2], 16) for i in (0, 2, 4)) + (255,)
    draw = ImageDraw.Draw(canvas)
    widths = []
    for seg, cjk in runs:
        f = f_cn if cjk else f_en
        widths.append(draw.textlength(seg, font=f))
    text_w = sum(widths)
    text_h = size

    # 文字在上、鞋图在下，整体居中于右侧空白区
    gap = int(CANVAS[1] * 0.05)
    block_h = text_h + gap + shoe.height
    top = (CANVAS[1] - block_h) // 2
    tx = area_x0 + (area_w - text_w) // 2
    ty = top
    for (seg, cjk), wd in zip(runs, widths):
        f = f_cn if cjk else f_en
        draw.text((tx, ty), seg, font=f, fill=color)
        tx += wd

    sx = area_x0 + (area_w - shoe.width) // 2
    sy = top + text_h + gap
    canvas.alpha_composite(shoe, (sx, sy))

    out = Path(args.out).expanduser()
    out.parent.mkdir(parents=True, exist_ok=True)
    canvas.convert("RGB").save(out, "PNG")
    print(json.dumps({
        "status": "ok", "out": str(out), "canvas": list(CANVAS),
        "font": "中英混排" if has_cjk else "Herculanum",
        "font_files": {"en": pick(FONT_EN, FONT_EN_ALT), "cn": pick(FONT_CN, FONT_CN_ALT)},
        "shoe_size": [shoe.width, shoe.height], "color": args.color,
        "faces": {"en": list(f_en.getname()), "cn": list(f_cn.getname())},
    }, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
