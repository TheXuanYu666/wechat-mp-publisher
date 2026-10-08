#!/usr/bin/env python3
"""搜最近比较火的鞋，生成候选表（references/candidates.json）。

数据源按可靠性排序：
  1. RunRepeat 分类榜（公开可抓，带人气排序）—— 跑鞋 + 篮球鞋
  2. istarshine 热榜（需要 ISTARSHINE_API_KEY，服务不稳时自动跳过）
再用 published.json 剔除已经写过的鞋款。

进度会按行输出 `PROGRESS <pct> <说明>`，方便调用方做进度条。

用法:
  hot_shoes.py --market overseas --out references/candidates_overseas.json --limit 6
  hot_shoes.py --market domestic --out references/candidates_domestic.json --limit 6
"""
from __future__ import annotations

import argparse
import datetime
import json
import os
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
DOMESTIC_CLI = Path.home() / ".kiro/skills/istarshine-domestic-web-wide-search/scripts/cli.js"
DOMESTIC_QUERY = ("(李宁 OR 安踏 OR 特步 OR 361度 OR 匹克 OR 鸿星尔克 OR 中乔 OR 多威) "
                  "跑鞋 dateRestrict:d30")
DOMESTIC_SKIP_RX = re.compile(
    r"(儿童|童鞋|男童|女童|孩子|不费妈|旋钮|中考|体测|休闲鞋|皮面|老爹鞋|旅游鞋|"
    r"越野|登山|徒步|户外鞋|仓库|搬空|同城好店)"
)
DOMESTIC_SERIES = [
    ("李宁", r"李宁", ["飞电", "赤兔", "越影", "超轻", "烈骏", "吾适", "绝影", "逐影"]),
    ("安踏", r"安踏", ["C202", "马赫", "柏油路霸", "氢跑", "羚跑", "毒刺", "火箭", "极影", "轻云", "凌风", "绝胜", "云途", "心率"]),
    ("特步", r"特步", ["160X", "260X", "300X", "360X", "两千公里", "2000KM", "氢风", "风火"]),
    ("361°", r"361(?:°|度)?", ["飞燃", "飚速", "爆沫", "赤焰", "速湃", "尖熠"]),
    ("匹克", r"匹克", ["UP30", "态极", "轻弹", "澎湃"]),
    ("鸿星尔克", r"鸿星尔克", ["芷境", "奇弹", "绝尘", "悦驰", "极风"]),
    ("中乔", r"(?:中乔|乔丹体育)", ["飞影", "风行", "强风", "毒牙"]),
    ("多威", r"多威", ["战神", "神行者", "飞影", "征途", "竞速", "飞扬"]),
]
MODEL_SUFFIX_RX = r"\s*((?:\d+(?:\.\d+)?|[一二三四五六七八九十]+代)?\s*(?:PRO|ULTRA|ELITE|CHALLENGER|LITE|SE|MAX)?)"


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



def _canonical_model(brand: str, series: str, suffix: str) -> str:
    suffix = re.sub(r"\s+", " ", suffix.strip()).upper()
    return f"{brand} {series}{suffix}".strip()


def parse_domestic_items(items: list[dict[str, Any]], limit: int) -> list[dict[str, Any]]:
    """从国内全网结果提取高置信度的国产专业跑鞋型号并按提及数排序。"""
    found: dict[str, dict[str, Any]] = {}
    seen_items: set[str] = set()
    for index, item in enumerate(items):
        title = str(item.get("title", ""))
        snippet = str(item.get("snippet", ""))
        text = re.sub(r"\s+", " ", f"{title} {snippet}").strip()
        item_key = str(item.get("link", "")) or norm(text)
        if not text or item_key in seen_items or DOMESTIC_SKIP_RX.search(text):
            continue
        seen_items.add(item_key)
        for brand, brand_rx, series_list in DOMESTIC_SERIES:
            if not re.search(brand_rx, text, re.I):
                continue
            for series in series_list:
                m = re.search(re.escape(series) + MODEL_SUFFIX_RX, text, re.I)
                if not m:
                    continue
                name = _canonical_model(brand, series, m.group(1))
                key = norm(name)
                row = found.setdefault(key, {
                    "name": name, "mentions": 0, "first": index,
                    "url": str(item.get("link", "")), "examples": [],
                })
                row["mentions"] += 1
                if title and title not in row["examples"] and len(row["examples"]) < 3:
                    row["examples"].append(title[:100])
    ranked = sorted(found.values(), key=lambda x: (-x["mentions"], x["first"], x["name"]))
    out = []
    for rank, row in enumerate(ranked[: max(limit * 3, limit)], 1):
        out.append({
            "name": row["name"], "rank": rank, "url": row["url"],
            "mentions": row["mentions"], "column": "跑鞋篇",
            "hot": f"国内全网近30天提及 {row['mentions']} 条（国产跑鞋热度第 {rank} 位）",
            "examples": row["examples"],
        })
    return out


def domestic_search_env() -> dict[str, str]:
    env = os.environ.copy()
    if env.get("ISTARSHINE_API_KEY"):
        return env
    try:
        key = subprocess.run([
            "/usr/bin/security", "find-generic-password", "-s",
            "wechat-mp-publisher.istarshine", "-a", Path.home().name, "-w",
        ], capture_output=True, text=True, timeout=10).stdout.strip()
        if key:
            env["ISTARSHINE_API_KEY"] = key
    except Exception:  # noqa: BLE001
        pass
    return env


def scrape_domestic(limit: int, timeout: int = 240) -> list[dict[str, Any]]:
    node = find_node()
    if not node or not DOMESTIC_CLI.exists():
        raise RuntimeError("找不到国内全网搜索工具")
    proc = subprocess.run([
        node, str(DOMESTIC_CLI), "search", "--cx", "posts", "--q", DOMESTIC_QUERY,
        "--num", "100", "--sort", "ctime:desc",
    ], capture_output=True, text=True, timeout=timeout, env=domestic_search_env())
    if proc.returncode != 0:
        raise RuntimeError(proc.stderr.strip()[-180:] or f"国内搜索退出码 {proc.returncode}")
    try:
        data = json.loads(proc.stdout)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"国内搜索返回无法解析：{exc}") from exc
    if isinstance(data.get("detail"), dict) and data["detail"].get("success") is False:
        raise RuntimeError(data["detail"].get("message") or data["detail"].get("error") or "国内搜索认证失败")
    items = data.get("items") or []
    candidates = parse_domestic_items(items, limit)
    if not candidates:
        raise RuntimeError("国内全网搜索有结果，但没有提取到具体国产专业跑鞋型号")
    return candidates

def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="搜最近比较火的鞋")
    ap.add_argument("--out", required=True)
    ap.add_argument("--limit", type=int, default=6)
    ap.add_argument("--market", choices=("overseas", "domestic"), default="overseas")
    ap.add_argument("--no-istarshine", action="store_true", help=argparse.SUPPRESS)
    args = ap.parse_args(argv)

    done = written()
    progress(5, f"读取已发台账，已写过 {len(done)} 双")

    pool: list[dict[str, Any]] = []
    errors: list[str] = []
    if args.market == "domestic":
        progress(15, "搜索国内近30天国产跑鞋热度")
        try:
            pool = scrape_domestic(args.limit)
        except Exception as exc:  # noqa: BLE001
            errors.append(str(exc))
        active_columns = ["跑鞋篇"]
        source_name = "istarshine 国内全网搜索"
    else:
        progress(15, "抓取国外跑鞋人气榜")
        column, url = CATALOGS[0]
        try:
            for c in scrape_catalog(url, args.limit):
                c["column"] = column
                c["hot"] = f"RunRepeat 国外跑鞋榜第 {c['rank']} 位（按人气排序）"
                pool.append(c)
        except Exception as exc:  # noqa: BLE001
            errors.append(f"{url}: {exc}")
        active_columns = ["跑鞋篇"]
        source_name = "RunRepeat 国外跑鞋榜"

    if not pool:
        print(json.dumps({"status": "no_candidates", "market": args.market,
                          "error": "；".join(errors) or "没有搜索结果"}, ensure_ascii=False))
        return 5
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
    for column in active_columns:
        sub = sorted([c for c in fresh if c["column"] == column], key=lambda x: x["rank"])
        picked += sub[: args.limit]
    for c in picked:
        c["has_article"] = norm(c["name"]) in local_articles
    local_marked = sum(1 for c in picked if c["has_article"])

    progress(90, "标注可复用的本地稿件")

    payload = {
        "_note": "由 hot_shoes.py 自动生成。查重只依据公众号后台已发表台账；本地稿件仅标注复用。",
        "market": args.market,
        "source_name": source_name,
        "updated": datetime.datetime.now().strftime("%Y-%m-%d %H:%M"),
        "sources": ([CATALOGS[0][1]] if args.market == "overseas" else ["istarshine-domestic-web-wide-search"]),
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
    print(json.dumps({"status": "ok", "market": args.market, "count": len(picked),
                      "excluded_written": excluded_published,
                      "excluded_published": excluded_published,
                      "local_articles_marked": local_marked,
                      "errors": errors, "out": str(out)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
