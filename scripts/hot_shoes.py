#!/usr/bin/env python3
"""搜最近比较火的鞋，生成候选表（references/candidates.json）。

数据源按可靠性排序：
  1. RunRepeat 分类榜（公开可抓，带人气排序）—— 跑鞋 + 篮球鞋
  2. istarshine 热榜（需要 ISTARSHINE_API_KEY，服务不稳时自动跳过）
再用 published.json 剔除已经写过的鞋款。

进度会按行输出 `PROGRESS <pct> <说明>`，方便调用方做进度条。

用法:
  hot_shoes.py --out references/candidates.json [--limit 6] [--no-istarshine]
"""
from __future__ import annotations

import argparse
import datetime
import json
import re
import subprocess
import sys
from pathlib import Path
from typing import Any

import requests

SKILL = Path(__file__).resolve().parent.parent
LEDGER = SKILL / "references" / "published.json"
UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36")
CATALOGS = [
    ("跑鞋篇", "https://runrepeat.com/catalog/running-shoes"),
    ("篮球鞋篇", "https://runrepeat.com/catalog/basketball-shoes"),
]
SKIP_RX = re.compile(r"^(Best|Top|How|Guide|Why|What|Compare)\b", re.I)


def progress(pct: int, msg: str) -> None:
    print(f"PROGRESS {pct} {msg}", flush=True)


def norm(s: str) -> str:
    return re.sub(r"[\s\-_°%’'\"()（）]", "", s).lower()


def written() -> set[str]:
    if not LEDGER.exists():
        return set()
    d = json.loads(LEDGER.read_text(encoding="utf-8"))
    out = set()
    for e in d.get("written", []):
        out.add(norm(e.get("name", "")))
        for a in e.get("aliases", []):
            out.add(norm(a))
    return {x for x in out if x}


def scrape_catalog(url: str, limit: int) -> list[dict[str, Any]]:
    r = requests.get(url, headers={"User-Agent": UA}, timeout=40)
    r.raise_for_status()
    names: list[str] = []
    for m in re.finditer(r'alt="([A-Z][\w\'\.\+\- ]{4,44})"', r.text):
        n = m.group(1).strip()
        if SKIP_RX.match(n) or n in names:
            continue
        names.append(n)
        if len(names) >= limit * 3:
            break
    out = []
    for i, n in enumerate(names, 1):
        slug = re.sub(r"[^a-z0-9]+", "-", n.lower()).strip("-")
        out.append({"name": n, "rank": i, "url": f"https://runrepeat.com/{slug}"})
    return out


def find_node() -> str | None:
    import shutil
    for c in (Path("/usr/local/bin/node"), Path("/opt/homebrew/bin/node")):
        if c.exists():
            return str(c)
    return shutil.which("node")


def istarshine_hot(timeout: int = 120) -> list[str]:
    cli = Path.home() / ".kiro/skills/istarshine-trending-search/scripts/cli.js"
    node = find_node()
    if not cli.exists() or not node:
        return []
    try:
        p = subprocess.run(
            [node, str(cli), "--task", "最近7天跑鞋和篮球鞋的热榜热搜，只列鞋款名称", "--json"],
            capture_output=True, text=True, timeout=timeout)
    except Exception:  # noqa: BLE001
        return []
    if p.returncode != 0:
        return []
    text = p.stdout
    hits = re.findall(r"[A-Z][A-Za-z]+(?: [A-Za-z0-9%°]+){1,4}", text)
    seen, out = set(), []
    for h in hits:
        k = norm(h)
        if k in seen or SKIP_RX.match(h):
            continue
        seen.add(k)
        out.append(h.strip())
    return out[:10]


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="搜最近比较火的鞋")
    ap.add_argument("--out", required=True)
    ap.add_argument("--limit", type=int, default=6)
    ap.add_argument("--no-istarshine", action="store_true")
    args = ap.parse_args(argv)

    done = written()
    progress(5, f"读取已发台账，已写过 {len(done)} 双")

    pool: list[dict[str, Any]] = []
    errors: list[str] = []
    pct = 10
    for column, url in CATALOGS:
        progress(pct, f"抓取 {column} 榜单")
        try:
            for c in scrape_catalog(url, args.limit):
                c["column"] = column
                c["hot"] = f"RunRepeat {column[:2]}榜第 {c['rank']} 位（按人气排序）"
                pool.append(c)
        except Exception as exc:  # noqa: BLE001
            errors.append(f"{url}: {exc}")
        pct += 30

    if not args.no_istarshine:
        progress(pct, "查 istarshine 热榜（不稳时自动跳过）")
        extra = istarshine_hot()
        for n in extra:
            if not any(norm(n) == norm(c["name"]) for c in pool):
                pool.append({"name": n, "column": "跑鞋篇", "rank": 99,
                             "hot": "istarshine 热榜提到", "url": ""})
        if not extra:
            errors.append("istarshine 热榜没返回可用结果")
    pct = 75

    progress(pct, "按公众号已发表台账查重")
    fresh = [c for c in pool if norm(c["name"]) not in done]
    excluded_published = len(pool) - len(fresh)

    # 查重只认公众号后台已发表内容。本地 article.json 不代表已发布，只标注可复用。
    if str(SKILL) not in sys.path:
        sys.path.insert(0, str(SKILL))
    from config import assets_root as _ar  # noqa: PLC0415
    root = _ar()
    local_articles: set[str] = set()
    if root.exists():
        try:
            local_articles = {
                norm(d.name) for d in root.iterdir()
                if d.is_dir() and (d / "article.json").exists()
            }
        except OSError:
            local_articles = set()

    # 只剔除已发表后，每个栏目各取前 limit 个；已有本地稿件照常进入热门候选。
    picked: list[dict[str, Any]] = []
    for column, _ in CATALOGS:
        sub = sorted([c for c in fresh if c["column"] == column], key=lambda x: x["rank"])
        picked += sub[: args.limit]
    for c in picked:
        c["has_article"] = norm(c["name"]) in local_articles
    local_marked = sum(1 for c in picked if c["has_article"])

    progress(90, "标注可复用的本地稿件")

    payload = {
        "_note": "由 hot_shoes.py 自动生成。查重只依据公众号后台已发表台账；本地稿件仅标注复用。",
        "updated": datetime.datetime.now().strftime("%Y-%m-%d %H:%M"),
        "sources": [u for _, u in CATALOGS],
        "excluded_written": excluded_published,
        "excluded_published": excluded_published,
        "local_articles_marked": local_marked,
        "errors": errors,
        "candidates": picked,
    }
    out = Path(args.out).expanduser()
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    progress(100, f"完成，候选 {len(picked)} 双")
    print(json.dumps({"status": "ok", "count": len(picked),
                      "excluded_written": excluded_published,
                      "excluded_published": excluded_published,
                      "local_articles_marked": local_marked,
                      "errors": errors, "out": str(out)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
