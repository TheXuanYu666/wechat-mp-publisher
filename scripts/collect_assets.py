#!/usr/bin/env python3
"""清点素材盘里某鞋款的实拍图，按本号惯用顺序排好，直接产出 article.json 的图块草稿。

素材盘约定（观察自 <素材盘>/<你的文件夹>）：
  步界社/<鞋款名>/{封面,正视图,侧视图,后视图,俯视图,正面,背面,鞋面,鞋底,中底图片,拆解图}.{png,webp,avif,jpg}
同名多格式时优先选公众号兼容且体积合适的：png > jpg > webp > avif（webp/avif 微信正文支持不稳）。
macOS 的 `._` AppleDouble 文件一律忽略。

用法:
  collect_assets.py list                                   # 列出所有鞋款目录
  collect_assets.py plan --shoe "Nike Zoom Fly 6"          # 出图块草稿
  collect_assets.py plan --shoe "飞燃3" --out imgs.json --copy-to ~/mp-posts/x/imgs
"""
from __future__ import annotations

import argparse
import json
import re
import shutil
import sys
from pathlib import Path

import sys as _s; _s.path.insert(0, str(Path(__file__).resolve().parent.parent))
from config import assets_root as _ar  # noqa: E402

DEFAULT_ROOT = _ar()
EXT_PRIORITY = [".png", ".jpg", ".jpeg", ".webp", ".avif"]
SAFE_EXT = {".png", ".jpg", ".jpeg"}

# 视角 → 归属章节（照本号发布版的图片分布）
VIEW_ORDER: list[tuple[str, str, str]] = [
    ("封面", "01", "开篇简介"),
    ("正视图", "02", "外观设计与做工"),
    ("正面", "02", "外观设计与做工"),
    ("侧视图", "02", "外观设计与做工"),
    ("后视图", "02", "外观设计与做工"),
    ("背面", "02", "外观设计与做工"),
    ("俯视图", "02", "外观设计与做工"),
    ("鞋面", "02", "外观设计与做工"),
    ("中底图片", "03", "中底性能"),
    ("拆解图", "03", "中底性能"),
    ("鞋底", "04", "外底与耐久性"),
    ("大底", "04", "外底与耐久性"),
]


def is_junk(p: Path) -> bool:
    return p.name.startswith("._") or p.name == ".DS_Store"


def shoe_dirs(root: Path) -> list[Path]:
    if not root.exists():
        return []
    return sorted(d for d in root.iterdir() if d.is_dir() and not is_junk(d))


def pick_variant(cands: list[Path]) -> Path:
    def key(p: Path) -> tuple[int, int]:
        ext = p.suffix.lower()
        return (EXT_PRIORITY.index(ext) if ext in EXT_PRIORITY else 99, -p.stat().st_size)

    return sorted(cands, key=key)[0]


def match_view(stem: str) -> tuple[str, str, str] | None:
    for view, num, title in VIEW_ORDER:
        if view in stem:
            return view, num, title
    return None


def collect(shoe_dir: Path) -> dict:
    files = [p for p in shoe_dir.rglob("*") if p.is_file() and not is_junk(p)]
    images = [p for p in files if p.suffix.lower() in EXT_PRIORITY]
    # 同视角合并多格式
    groups: dict[str, list[Path]] = {}
    unmatched: list[str] = []
    for p in images:
        hit = match_view(p.stem)
        if not hit:
            unmatched.append(str(p.relative_to(shoe_dir)))
            continue
        groups.setdefault(hit[0], []).append(p)

    picked: list[dict] = []
    for view, num, title in VIEW_ORDER:
        if view not in groups:
            continue
        best = pick_variant(groups[view])
        picked.append(
            {
                "view": view,
                "section": num,
                "section_title": title,
                "path": str(best),
                "ext": best.suffix.lower(),
                "size_kb": round(best.stat().st_size / 1024),
                "wechat_safe": best.suffix.lower() in SAFE_EXT,
                "variants": [str(x) for x in sorted(groups[view])],
            }
        )
    others = {
        "psd": [str(p) for p in files if p.suffix.lower() == ".psd"],
        "video": [str(p) for p in files if p.suffix.lower() in (".mov", ".mp4")],
        "text": [str(p) for p in files if p.suffix.lower() in (".txt", ".srt", ".pages", ".docx")],
    }
    return {"shoe": shoe_dir.name, "dir": str(shoe_dir), "images": picked,
            "unmatched_images": unmatched, "others": others}


def cmd_list(args: argparse.Namespace) -> int:
    root = Path(args.root).expanduser()
    dirs = shoe_dirs(root)
    if not dirs:
        print(json.dumps({"status": "not_found", "root": str(root),
                          "hint": "素材盘没挂载？确认 /Volumes 下的卷名"}, ensure_ascii=False, indent=2))
        return 7
    out = []
    for d in dirs:
        info = collect(d)
        out.append({"shoe": info["shoe"], "images": len(info["images"]),
                    "views": [i["view"] for i in info["images"]],
                    "unmatched": len(info["unmatched_images"])})
    print(json.dumps({"status": "ok", "root": str(root), "shoes": out}, ensure_ascii=False, indent=2))
    return 0


def cmd_plan(args: argparse.Namespace) -> int:
    root = Path(args.root).expanduser()
    dirs = shoe_dirs(root)
    if not dirs:
        print(json.dumps({"status": "not_found", "root": str(root)}, ensure_ascii=False, indent=2))
        return 7
    want = args.shoe.lower().replace(" ", "")
    hit = next((d for d in dirs if want in d.name.lower().replace(" ", "")), None)
    if hit is None:
        print(json.dumps({"status": "no_such_shoe", "shoe": args.shoe,
                          "available": [d.name for d in dirs]}, ensure_ascii=False, indent=2))
        return 7
    info = collect(hit)

    if args.copy_to:
        dst = Path(args.copy_to).expanduser()
        dst.mkdir(parents=True, exist_ok=True)
        for im in info["images"]:
            src = Path(im["path"])
            target = dst / f'{im["section"]}_{im["view"]}{src.suffix.lower()}'
            shutil.copy2(src, target)
            im["local_copy"] = str(target)

    by_section: dict[str, list[dict]] = {}
    for im in info["images"]:
        key = f'{im["section"]} {im["section_title"]}'
        by_section.setdefault(key, []).append(
            {"type": "img", "url": "TODO_上传素材库后回填", "_source": im.get("local_copy") or im["path"],
             "_view": im["view"]}
        )

    warn = []
    unsafe = [i["view"] for i in info["images"] if not i["wechat_safe"]]
    if unsafe:
        warn.append(f"这些视角只挑到 webp/avif（{unsafe}），微信正文支持不稳，建议转成 png/jpg")
    # 历史每篇只用 4 张实拍（01–04 各一张），子标题装饰条由渲染器自动插
    need = 4
    if len(info["images"]) < need:
        warn.append(f"只找到 {len(info['images'])} 张实拍，历史每篇需要 {need} 张（01–04 各一张）")
    else:
        warn.append(
            f"可用实拍 {len(info['images'])} 张，历史每篇用 {need} 张："
            "01 建议用封面/整体，02 用外观细节，03 用中底，04 用鞋底"
        )

    payload = {"status": "ok", "shoe": info["shoe"], "dir": info["dir"],
               "image_count": len(info["images"]), "img_blocks_by_section": by_section,
               "cover_psd": info["others"]["psd"], "unmatched_images": info["unmatched_images"],
               "warnings": warn}
    if args.out:
        Path(args.out).expanduser().write_text(
            json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="素材盘图片清点")
    ap.add_argument("--root", default=str(DEFAULT_ROOT))
    sub = ap.add_subparsers(dest="cmd", required=True)
    a = sub.add_parser("list"); a.set_defaults(func=cmd_list)
    b = sub.add_parser("plan")
    b.add_argument("--shoe", required=True)
    b.add_argument("--out")
    b.add_argument("--copy-to")
    b.set_defaults(func=cmd_plan)
    args = ap.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
