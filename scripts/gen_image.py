#!/usr/bin/env python3
"""配图生成：网上搜不到可用图片时，用 AI 生成；没有 API key 时退化为本地文字卡。

优先级：
  1. --provider openai    需要 OPENAI_API_KEY（模型默认 gpt-image-1）
  2. --provider dashscope 需要 DASHSCOPE_API_KEY（通义万相）
  3. --provider card      纯本地 Pillow 文字卡，永不失败，可做小标题分隔图/数据卡

用法:
  gen_image.py --prompt "白色跑鞋侧面产品图，纯色背景，柔和光线" --out cover.png
  gen_image.py --provider card --title "二级市场价格速览" --subtitle "数据来源：得物" --out card.png
注意:
  不要生成任何带真实品牌 logo 的伪造产品图去冒充实拍；生成图必须在图注里标注"AI 生成示意图"。
"""
from __future__ import annotations

import argparse
import base64
import json
import os
import sys
import time
from pathlib import Path

MAC_FONTS = [
    "/System/Library/Fonts/PingFang.ttc",
    "/System/Library/Fonts/Hiragino Sans GB.ttc",
    "/Library/Fonts/Arial Unicode.ttf",
    "/System/Library/Fonts/Supplemental/Songti.ttc",
]


def pick_font(size: int):
    from PIL import ImageFont

    for p in MAC_FONTS:
        if Path(p).exists():
            try:
                return ImageFont.truetype(p, size)
            except Exception:  # noqa: BLE001
                continue
    return ImageFont.load_default()


def wrap_cjk(text: str, per_line: int) -> list[str]:
    lines, cur = [], ""
    for ch in text:
        cur += ch
        if len(cur) >= per_line:
            lines.append(cur)
            cur = ""
    if cur:
        lines.append(cur)
    return lines


def make_card(out: Path, title: str, subtitle: str, accent: str, size: tuple[int, int]) -> dict:
    from PIL import Image, ImageDraw

    w, h = size
    img = Image.new("RGB", (w, h), "#ffffff")
    d = ImageDraw.Draw(img)
    d.rectangle([0, 0, w, 10], fill=accent)
    d.rectangle([0, h - 6, w, h], fill="#eeeeee")

    tf = pick_font(int(w * 0.075))
    sf = pick_font(int(w * 0.036))
    y = int(h * 0.30)
    for line in wrap_cjk(title, 12)[:3]:
        d.text((int(w * 0.08), y), line, font=tf, fill="#1f1f1f")
        y += int(w * 0.10)
    if subtitle:
        y += int(h * 0.03)
        for line in wrap_cjk(subtitle, 24)[:3]:
            d.text((int(w * 0.08), y), line, font=sf, fill="#8a8a8a")
            y += int(w * 0.055)
    d.line([int(w * 0.08), int(h * 0.24), int(w * 0.22), int(h * 0.24)], fill=accent, width=6)
    out.parent.mkdir(parents=True, exist_ok=True)
    img.save(out, "PNG")
    return {"provider": "card", "path": str(out), "width": w, "height": h, "ai_generated": True}


def gen_openai(prompt: str, out: Path, size: str, model: str) -> dict:
    import requests

    key = os.environ.get("OPENAI_API_KEY")
    if not key:
        raise RuntimeError("未设置 OPENAI_API_KEY")
    base = os.environ.get("OPENAI_BASE_URL", "https://api.openai.com/v1").rstrip("/")
    resp = requests.post(
        f"{base}/images/generations",
        headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
        json={"model": model, "prompt": prompt, "size": size, "n": 1},
        timeout=180,
    )
    if resp.status_code >= 400:
        raise RuntimeError(f"OpenAI 返回 {resp.status_code}: {resp.text[:300]}")
    data = resp.json()["data"][0]
    out.parent.mkdir(parents=True, exist_ok=True)
    if data.get("b64_json"):
        out.write_bytes(base64.b64decode(data["b64_json"]))
    else:
        img = requests.get(data["url"], timeout=180)
        img.raise_for_status()
        out.write_bytes(img.content)
    return {"provider": "openai", "model": model, "path": str(out), "ai_generated": True}


def gen_dashscope(prompt: str, out: Path, size: str, model: str) -> dict:
    import requests

    key = os.environ.get("DASHSCOPE_API_KEY")
    if not key:
        raise RuntimeError("未设置 DASHSCOPE_API_KEY")
    create = requests.post(
        "https://dashscope.aliyuncs.com/api/v1/services/aigc/text2image/image-synthesis",
        headers={
            "Authorization": f"Bearer {key}",
            "Content-Type": "application/json",
            "X-DashScope-Async": "enable",
        },
        json={
            "model": model,
            "input": {"prompt": prompt},
            "parameters": {"size": size.replace("x", "*"), "n": 1},
        },
        timeout=60,
    )
    if create.status_code >= 400:
        raise RuntimeError(f"DashScope 创建任务失败 {create.status_code}: {create.text[:300]}")
    task_id = create.json()["output"]["task_id"]
    url = None
    for _ in range(60):
        time.sleep(3)
        q = requests.get(
            f"https://dashscope.aliyuncs.com/api/v1/tasks/{task_id}",
            headers={"Authorization": f"Bearer {key}"},
            timeout=60,
        )
        out_j = q.json().get("output", {})
        status = out_j.get("task_status")
        if status == "SUCCEEDED":
            url = out_j["results"][0]["url"]
            break
        if status in ("FAILED", "CANCELED", "UNKNOWN"):
            raise RuntimeError(f"DashScope 任务 {status}: {json.dumps(out_j, ensure_ascii=False)[:300]}")
    if not url:
        raise RuntimeError("DashScope 任务超时")
    img = requests.get(url, timeout=180)
    img.raise_for_status()
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_bytes(img.content)
    return {"provider": "dashscope", "model": model, "path": str(out), "ai_generated": True}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="生成配图")
    ap.add_argument("--provider", default="auto", choices=["auto", "openai", "dashscope", "card"])
    ap.add_argument("--prompt", default="")
    ap.add_argument("--title", default="", help="card 模式主文案")
    ap.add_argument("--subtitle", default="", help="card 模式副文案")
    ap.add_argument("--accent", default="#c0392b")
    ap.add_argument("--size", default="1024x1024")
    ap.add_argument("--model", default="", help="openai 默认 gpt-image-1，dashscope 默认 wanx2.1-t2i-turbo")
    ap.add_argument("--out", required=True)
    ap.add_argument("--fallback-card", action="store_true", help="AI 失败时自动退化为文字卡")
    args = ap.parse_args(argv)

    out = Path(args.out).expanduser()
    order: list[str]
    if args.provider == "auto":
        order = []
        if os.environ.get("OPENAI_API_KEY"):
            order.append("openai")
        if os.environ.get("DASHSCOPE_API_KEY"):
            order.append("dashscope")
        order.append("card")
    else:
        order = [args.provider]
        if args.fallback_card and args.provider != "card":
            order.append("card")

    errors: list[str] = []
    for prov in order:
        try:
            if prov == "card":
                title = args.title or args.prompt[:24] or "示意图"
                w, h = (int(x) for x in args.size.lower().split("x"))
                res = make_card(out, title, args.subtitle, args.accent, (w, h))
            elif prov == "openai":
                if not args.prompt:
                    raise RuntimeError("openai 需要 --prompt")
                res = gen_openai(args.prompt, out, args.size, args.model or "gpt-image-1")
            else:
                if not args.prompt:
                    raise RuntimeError("dashscope 需要 --prompt")
                res = gen_dashscope(args.prompt, out, args.size, args.model or "wanx2.1-t2i-turbo")
            res["status"] = "ok"
            res["errors"] = errors
            res["caption_required"] = "AI 生成示意图，非产品实拍"
            print(json.dumps(res, ensure_ascii=False, indent=2))
            return 0
        except Exception as exc:  # noqa: BLE001
            errors.append(f"{prov}: {exc}")

    print(json.dumps({"status": "failed", "errors": errors}, ensure_ascii=False, indent=2))
    return 5


if __name__ == "__main__":
    sys.exit(main())
