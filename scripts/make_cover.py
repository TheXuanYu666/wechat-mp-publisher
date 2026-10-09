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
    """Split shoe name into (segment, is_CJK) tuples for different fonts.
    Domestic shoes (with CJK): digits use Xingkai (harmonize with Chinese), English letters use Herculanum.
    Overseas shoes: all digits and letters use Herculanum.

    把鞋名切成(片段,是否中文)序列，中英分别用不同字体。
    国产鞋数字用行楷与中文协调，英文字母用Herculanum；纯英文鞋全用Herculanum。
    """
    has_cjk = bool(CJK_RX.search(text))
    runs: list[tuple[str, bool]] = []
    for ch in text:
        # 中文字符本身、或者是国产鞋里的数字，算"中文片段"用行楷；
        # 国产鞋的英文字母、纯英文鞋的所有内容都算"英文片段"用Herculanum
        cjk = bool(CJK_RX.match(ch)) or (has_cjk and ch.isdigit())
        if runs and runs[-1][1] == cjk:
            runs[-1] = (runs[-1][0] + ch, cjk)
        else:
            runs.append((ch, cjk))
    return runs


def _num(value, default: float) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _element(layout: dict, name: str, default_x: int, default_y: int,
             base_w: int, base_h: int, min_scale: float, max_scale: float) -> dict[str, float | int]:
    """把前端布局约束在画布内，返回可直接绘制的实际框。"""
    requested = layout.get(name) if isinstance(layout.get(name), dict) else {}
    scale = max(min_scale, min(max_scale, _num(requested.get("scale"), 1.0)))
    # 不允许缩放后比整个画布还大。
    scale = min(scale, CANVAS[0] / max(1, base_w), CANVAS[1] / max(1, base_h))
    w, h = max(1, round(base_w * scale)), max(1, round(base_h * scale))
    x = round(_num(requested.get("x"), default_x))
    y = round(_num(requested.get("y"), default_y))
    x = max(0, min(CANVAS[0] - w, x))
    y = max(0, min(CANVAS[1] - h, y))
    return {"x": x, "y": y, "w": w, "h": h, "scale": round(scale, 4)}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="生成公众号封面")
    ap.add_argument("--shoe", required=True)
    ap.add_argument("--side-view", required=True, help="鞋的侧视图（会自动去白底）")
    ap.add_argument("--out", required=True)
    ap.add_argument("--color", default="#884b3f", help="鞋名文字颜色")
    ap.add_argument("--shoe-height", type=float, default=0.62,
                    help="鞋图默认高度占画布比例")
    ap.add_argument("--layout-json", default="",
                    help='元素布局 JSON：shoe/text/logo 各含 x、y、scale')
    args = ap.parse_args(argv)

    try:
        requested_layout = json.loads(args.layout_json) if args.layout_json else {}
        if not isinstance(requested_layout, dict):
            raise ValueError("layout 必须是对象")
    except (json.JSONDecodeError, ValueError) as exc:
        print(json.dumps({"status": "bad_layout", "error": str(exc)}, ensure_ascii=False))
        return 3

    sv = Path(args.side_view).expanduser()
    if not sv.exists():
        print(json.dumps({"status": "no_side_view", "path": str(sv)}, ensure_ascii=False))
        return 2

    # 先得到鞋图默认基准尺寸；前端 scale 始终相对这个尺寸，反复编辑不会累积误差。
    shoe_source = trim_bg(Image.open(sv))
    base_shoe_h = max(1, int(CANVAS[1] * max(0.1, min(0.95, args.shoe_height))))
    ratio = base_shoe_h / max(1, shoe_source.height)
    base_shoe_w = max(1, int(shoe_source.width * ratio))
    area_x0, area_x1 = LOGO_BOX[2], CANVAS[0]
    area_w = area_x1 - area_x0
    if base_shoe_w > area_w * 0.92:
        r2 = (area_w * 0.92) / base_shoe_w
        base_shoe_w, base_shoe_h = int(base_shoe_w * r2), int(base_shoe_h * r2)

    runs = split_runs(args.shoe)
    has_cjk = any(c for _, c in runs)
    base_font_size = 125 if has_cjk else 100
    text_req = requested_layout.get("text") if isinstance(requested_layout.get("text"), dict) else {}
    text_scale = max(0.45, min(2.0, _num(text_req.get("scale"), 1.0)))
    font_size = max(18, round(base_font_size * text_scale))
    f_en = load_font(pick(FONT_EN, FONT_EN_ALT), font_size, ("Herculanum", "Regular"))
    f_cn = load_font(pick(FONT_CN, FONT_CN_ALT), font_size, ("Xingkai SC", "Light"))
    measure = ImageDraw.Draw(Image.new("RGBA", (1, 1)))
    widths = [measure.textlength(seg, font=f_cn if cjk else f_en) for seg, cjk in runs]
    text_w, text_h = max(1, int(sum(widths) + 1)), font_size
    if text_w > CANVAS[0]:
        text_scale *= CANVAS[0] / text_w
        font_size = max(18, round(base_font_size * text_scale))
        f_en = load_font(pick(FONT_EN, FONT_EN_ALT), font_size, ("Herculanum", "Regular"))
        f_cn = load_font(pick(FONT_CN, FONT_CN_ALT), font_size, ("Xingkai SC", "Light"))
        widths = [measure.textlength(seg, font=f_cn if cjk else f_en) for seg, cjk in runs]
        text_w, text_h = max(1, int(sum(widths) + 1)), font_size

    # 使用当前缩放值计算默认居中位置；前端传 x/y 后则按用户位置。
    shoe_req = requested_layout.get("shoe") if isinstance(requested_layout.get("shoe"), dict) else {}
    shoe_scale = max(0.25, min(1.6, _num(shoe_req.get("scale"), 1.0)))
    preview_shoe_w, preview_shoe_h = round(base_shoe_w * shoe_scale), round(base_shoe_h * shoe_scale)
    gap = int(CANVAS[1] * 0.05)
    top = (CANVAS[1] - (text_h + gap + preview_shoe_h)) // 2
    default_tx = area_x0 + (area_w - text_w) // 2
    default_sx = area_x0 + (area_w - preview_shoe_w) // 2

    text_box = {
        "x": max(0, min(CANVAS[0] - text_w, round(_num(text_req.get("x"), default_tx)))),
        "y": max(0, min(CANVAS[1] - text_h, round(_num(text_req.get("y"), top)))),
        "w": text_w, "h": text_h, "scale": round(text_scale, 4),
    }
    shoe_box = _element(requested_layout, "shoe", default_sx, top + text_h + gap,
                        base_shoe_w, base_shoe_h, 0.25, 1.6)
    logo_box = _element(requested_layout, "logo", LOGO_BOX[0], LOGO_BOX[1],
                        LOGO_BOX[2] - LOGO_BOX[0], LOGO_BOX[3] - LOGO_BOX[1], 0.25, 1.5)

    canvas = Image.new("RGBA", CANVAS, (255, 255, 255, 255))
    if LOGO.exists():
        logo = Image.open(LOGO).convert("RGBA").resize(
            (int(logo_box["w"]), int(logo_box["h"])), Image.LANCZOS)
        canvas.alpha_composite(logo, (int(logo_box["x"]), int(logo_box["y"])))

    c = args.color.lstrip("#")
    color = tuple(int(c[i:i + 2], 16) for i in (0, 2, 4)) + (255,)
    draw = ImageDraw.Draw(canvas)
    tx = float(text_box["x"])
    for (seg, cjk), wd in zip(runs, widths):
        draw.text((tx, int(text_box["y"])), seg, font=f_cn if cjk else f_en, fill=color)
        tx += wd

    shoe = shoe_source.resize((int(shoe_box["w"]), int(shoe_box["h"])), Image.LANCZOS)
    canvas.alpha_composite(shoe, (int(shoe_box["x"]), int(shoe_box["y"])))

    out = Path(args.out).expanduser()
    out.parent.mkdir(parents=True, exist_ok=True)
    canvas.convert("RGB").save(out, "PNG")
    print(json.dumps({
        "status": "ok", "out": str(out), "canvas": list(CANVAS),
        "font": "中英混排" if has_cjk else "Herculanum",
        "font_files": {"en": pick(FONT_EN, FONT_EN_ALT), "cn": pick(FONT_CN, FONT_CN_ALT)},
        "shoe_size": [shoe.width, shoe.height], "color": args.color,
        "faces": {"en": list(f_en.getname()), "cn": list(f_cn.getname())},
        "layout": {"shoe": shoe_box, "text": text_box, "logo": logo_box},
    }, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
