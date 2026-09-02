#!/usr/bin/env python3
"""从历史公众号文章反推排版规范，输出 style_profile.json。

输入可以是公开分享链接（https://mp.weixin.qq.com/s/xxx）或本地已保存的 HTML。
只读取公开页面，不接触后台登录态。

用法:
  learn_style.py --url https://mp.weixin.qq.com/s/AAA --url https://mp.weixin.qq.com/s/BBB \
      --out ~/.kiro/skills/wechat-mp-publisher/references/style_profile.json
  learn_style.py --html ./saved1.html --html ./saved2.html --out profile.json
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

try:
    from bs4 import BeautifulSoup
except ImportError:  # pragma: no cover
    sys.exit("缺少依赖 beautifulsoup4，请先执行 pip install -r requirements.txt")

UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
)

# 关心的 CSS 属性
TRACKED_PROPS = (
    "font-size",
    "line-height",
    "color",
    "letter-spacing",
    "text-align",
    "font-weight",
    "background-color",
    "background",
    "border-left",
    "border-top",
    "border-bottom",
    "border-radius",
    "padding",
    "margin",
    "margin-top",
    "margin-bottom",
    "font-family",
    "text-indent",
)

NEUTRAL_COLORS = {
    "#000",
    "#000000",
    "#333",
    "#333333",
    "#3f3f3f",
    "#444",
    "#444444",
    "#555",
    "#555555",
    "#666",
    "#666666",
    "#777",
    "#888",
    "#999",
    "#fff",
    "#ffffff",
    "rgb(0,0,0)",
    "rgb(51,51,51)",
    "rgb(62,62,62)",
    "rgb(63,63,63)",
    "rgb(255,255,255)",
    "inherit",
    "initial",
}

HEADING_PATTERNS = [
    ("numbered_cn", re.compile(r"^\s*[一二三四五六七八九十]+[、.．]")),
    ("numbered_ar", re.compile(r"^\s*\d{1,2}[、.．)）]")),
    ("bracket", re.compile(r"^\s*[【\[（(].{1,20}[】\])）]")),
    ("emoji", re.compile(r"^\s*[\U0001F300-\U0001FAFF\u2600-\u27BF]")),
    ("pipe", re.compile(r"^\s*[|｜]")),
]

DISCLAIMER_HINT = re.compile(r"(仅供参考|不构成|价格|以实际|数据来源|来源[:：]|免责)")
CTA_HINT = re.compile(r"(关注|点赞|在看|评论|转发|留言|星标|分享)")


def parse_style(raw: str) -> dict[str, str]:
    out: dict[str, str] = {}
    for decl in (raw or "").split(";"):
        if ":" not in decl:
            continue
        k, _, v = decl.partition(":")
        k = k.strip().lower()
        v = " ".join(v.split()).strip().lower()
        if k in TRACKED_PROPS and v:
            out[k] = v
    return out


def norm_color(v: str) -> str:
    v = v.replace(" ", "").lower()
    m = re.match(r"^#([0-9a-f]{3})$", v)
    if m:
        v = "#" + "".join(c * 2 for c in m.group(1))
    return v


def px(v: str | None) -> float | None:
    if not v:
        return None
    m = re.match(r"^(-?\d+(?:\.\d+)?)\s*px$", v.strip())
    return float(m.group(1)) if m else None


def fetch(url: str, timeout: int = 30) -> str:
    import requests

    resp = requests.get(url, headers={"User-Agent": UA}, timeout=timeout)
    resp.raise_for_status()
    resp.encoding = resp.apparent_encoding or "utf-8"
    return resp.text


def content_root(soup: BeautifulSoup):
    for sel in ("#js_content", "div.rich_media_content", "#page-content"):
        node = soup.select_one(sel)
        if node is not None:
            return node
    return soup.body or soup


def text_of(node) -> str:
    return " ".join(node.get_text(" ", strip=True).split())


class Sample:
    """单篇文章的抽取结果。"""

    def __init__(self, label: str, html: str):
        soup = BeautifulSoup(html, "lxml")
        self.label = label
        title_node = soup.select_one("#activity-name, h1.rich_media_title, h1")
        self.title = text_of(title_node) if title_node else ""
        acct = soup.select_one("#js_name, .rich_media_meta_nickname")
        self.account = text_of(acct) if acct else ""
        self.root = content_root(soup)
        self.blocks: list[dict[str, Any]] = []
        self.styles: dict[str, Counter] = defaultdict(Counter)
        self.colors: Counter = Counter()
        self.bg_colors: Counter = Counter()
        self.font_families: Counter = Counter()
        self._walk()

    # -- 内部 ------------------------------------------------------------
    def _record_styles(self, role: str, style: dict[str, str]) -> None:
        for k, v in style.items():
            if k in ("color",):
                v = norm_color(v)
                if v not in NEUTRAL_COLORS:
                    self.colors[v] += 1
            if k in ("background-color", "background"):
                v2 = norm_color(v)
                if v2 not in NEUTRAL_COLORS and "url(" not in v2:
                    self.bg_colors[v2] += 1
            if k == "font-family":
                self.font_families[v] += 1
            self.styles[f"{role}.{k}"][v] += 1

    def _effective_style(self, node) -> dict[str, str]:
        """块自身样式 + 首个 span/strong 子元素样式（公众号常把样式写在 span 上）。"""
        style = parse_style(node.get("style", ""))
        for child in node.find_all(["span", "strong", "b", "em"], recursive=True)[:3]:
            for k, v in parse_style(child.get("style", "")).items():
                style.setdefault(k, v)
        return style

    def _classify(self, node, style: dict[str, str], text: str) -> str:
        tag = node.name
        if tag in ("h1", "h2", "h3", "h4"):
            return "h2" if tag in ("h1", "h2") else "h3"
        size = px(style.get("font-size"))
        weight = style.get("font-weight", "")
        bold = weight in ("bold", "bolder") or (weight.isdigit() and int(weight) >= 600)
        has_strong = node.find(["strong", "b"]) is not None
        short = len(text) <= 30
        if short and (size or 0) >= 17:
            return "h2"
        if short and (bold or has_strong):
            return "h3"
        if style.get("border-left") or (
            style.get("background-color")
            and norm_color(style["background-color"]) not in NEUTRAL_COLORS
        ):
            return "quote"
        return "p"

    def _walk(self) -> None:
        img_seen = 0
        children = [
            c
            for c in self.root.find_all(
                ["p", "section", "h1", "h2", "h3", "h4", "blockquote", "ul", "ol", "table", "hr"],
                recursive=True,
            )
        ]
        for node in children:
            # section 常作为容器，只有直接含文本时才算块
            if node.name == "section" and node.find(["p", "section", "table", "ul", "ol"]):
                # 容器：仍记录其样式（可能承载卡片背景）
                st = parse_style(node.get("style", ""))
                if st:
                    self._record_styles("container", st)
                continue
            if node.name == "hr":
                self.blocks.append({"type": "hr"})
                continue
            if node.name == "table":
                st = self._effective_style(node)
                self._record_styles("table", st)
                head = node.find("tr")
                if head:
                    for cell in head.find_all(["th", "td"]):
                        self._record_styles("table_header", parse_style(cell.get("style", "")))
                for cell in node.find_all("td")[:24]:
                    self._record_styles("table_cell", parse_style(cell.get("style", "")))
                self.blocks.append(
                    {
                        "type": "table",
                        "cols": len(head.find_all(["td", "th"])) if head else 0,
                        "rows": len(node.find_all("tr")),
                    }
                )
                continue
            if node.name in ("ul", "ol"):
                st = self._effective_style(node)
                self._record_styles("list", st)
                self.blocks.append({"type": "list", "items": len(node.find_all("li"))})
                continue

            imgs = node.find_all("img")
            text = text_of(node)
            if imgs and not text:
                for im in imgs:
                    st = parse_style(im.get("style", ""))
                    self._record_styles("img", st)
                    img_seen += 1
                    self.blocks.append({"type": "img"})
                continue
            if not text:
                # 公众号常用带 border 的空段落当分割线
                st = parse_style(node.get("style", ""))
                if st.get("border-top") or st.get("border-bottom"):
                    self._record_styles("hr", st)
                    self.blocks.append({"type": "hr"})
                continue

            style = self._effective_style(node)
            role = self._classify(node, style, text)
            # 图片后紧跟的短居中文本视为图注
            if (
                role == "p"
                and len(text) <= 40
                and style.get("text-align") == "center"
                and self.blocks
                and self.blocks[-1]["type"] == "img"
            ):
                role = "caption"
            self._record_styles(role, style)
            self.blocks.append({"type": role, "chars": len(text), "text": text[:120]})

        self.img_count = img_seen

    # -- 派生指标 --------------------------------------------------------
    def paragraph_chars(self) -> list[int]:
        return [b["chars"] for b in self.blocks if b["type"] == "p"]

    def total_chars(self) -> int:
        return sum(b.get("chars", 0) for b in self.blocks)

    def heading_texts(self) -> list[str]:
        return [b["text"] for b in self.blocks if b["type"] in ("h2", "h3")]

    def opening(self) -> str:
        for b in self.blocks:
            if b["type"] == "p" and b.get("chars", 0) > 10:
                return b["text"]
        return ""

    def closing(self) -> list[str]:
        tail = [b["text"] for b in self.blocks if b["type"] in ("p", "quote")][-3:]
        return tail


def mode(counter: Counter, default=None):
    return counter.most_common(1)[0][0] if counter else default


def build_profile(samples: list[Sample]) -> dict[str, Any]:
    agg: dict[str, Counter] = defaultdict(Counter)
    colors: Counter = Counter()
    bgs: Counter = Counter()
    fams: Counter = Counter()
    for s in samples:
        for k, c in s.styles.items():
            agg[k].update(c)
        colors.update(s.colors)
        bgs.update(s.bg_colors)
        fams.update(s.font_families)

    def pick(role: str, prop: str, default=None):
        return mode(agg.get(f"{role}.{prop}", Counter()), default)

    para_chars: list[int] = []
    for s in samples:
        para_chars.extend(s.paragraph_chars())
    para_chars.sort()
    avg_para = round(sum(para_chars) / len(para_chars)) if para_chars else 90
    med_para = para_chars[len(para_chars) // 2] if para_chars else 90

    headings: list[str] = []
    for s in samples:
        headings.extend(s.heading_texts())
    pat_counter: Counter = Counter()
    for h in headings:
        for name, rx in HEADING_PATTERNS:
            if rx.match(h):
                pat_counter[name] += 1
                break
        else:
            pat_counter["plain"] += 1

    totals = [s.total_chars() for s in samples] or [0]
    imgs = [s.img_count for s in samples] or [0]

    closings: list[str] = []
    for s in samples:
        closings.extend(s.closing())

    accent = mode(colors, "#c0392b")

    profile: dict[str, Any] = {
        "schema": 1,
        "learned_from": [{"label": s.label, "title": s.title, "account": s.account} for s in samples],
        "accent_color": accent,
        "secondary_colors": [c for c, _ in colors.most_common(5)],
        "background_colors": [c for c, _ in bgs.most_common(5)],
        "font_family": mode(fams, None),
        "css": {
            "body": {
                "font-size": pick("p", "font-size", "15px"),
                "line-height": pick("p", "line-height", "1.75"),
                "color": pick("p", "color", "#3f3f3f"),
                "letter-spacing": pick("p", "letter-spacing", "0.5px"),
                "text-align": pick("p", "text-align", "justify"),
                "margin-bottom": pick("p", "margin-bottom", "18px"),
                "text-indent": pick("p", "text-indent", "0"),
            },
            "h2": {
                "font-size": pick("h2", "font-size", "18px"),
                "color": pick("h2", "color", accent),
                "font-weight": pick("h2", "font-weight", "bold"),
                "text-align": pick("h2", "text-align", "left"),
                "margin": pick("h2", "margin", "32px 0 14px"),
                "line-height": pick("h2", "line-height", "1.5"),
            },
            "h3": {
                "font-size": pick("h3", "font-size", "16px"),
                "color": pick("h3", "color", "#222222"),
                "font-weight": pick("h3", "font-weight", "bold"),
                "margin": pick("h3", "margin", "22px 0 10px"),
            },
            "quote": {
                "font-size": pick("quote", "font-size", "14px"),
                "color": pick("quote", "color", "#666666"),
                "background-color": mode(agg.get("quote.background-color", Counter()), "#f7f7f7"),
                "border-left": pick("quote", "border-left", f"3px solid {accent}"),
                "padding": pick("quote", "padding", "12px 14px"),
                "margin": pick("quote", "margin", "18px 0"),
            },
            "caption": {
                "font-size": pick("caption", "font-size", "12px"),
                "color": pick("caption", "color", "#999999"),
                "text-align": "center",
                "margin": pick("caption", "margin", "6px 0 20px"),
            },
            "img": {
                "width": "100%",
                "border-radius": pick("img", "border-radius", "4px"),
                "display": "block",
                "margin": "0 auto",
            },
            "table": {
                "font-size": pick("table", "font-size") or pick("table_cell", "font-size", "13px"),
                "border": pick("table_cell", "border") or pick("table", "border", "1px solid #e6e6e6"),
                "header_bg": mode(
                    agg.get("table_header.background-color", Counter()),
                    mode(agg.get("table_header.background", Counter()), "#f5f5f5"),
                ),
                "header_color": pick("table_header", "color", "#222222"),
            },
            "hr": {
                "border-top": pick("hr", "border-top") or pick("hr", "border-bottom", "1px solid #e6e6e6"),
                "margin": pick("hr", "margin", "26px 0"),
            },
        },
        "structure": {
            "heading_pattern": mode(pat_counter, "plain"),
            "heading_pattern_counts": dict(pat_counter),
            "heading_samples": headings[:20],
            "avg_paragraph_chars": avg_para,
            "median_paragraph_chars": med_para,
            "max_paragraph_chars": int(para_chars[-1]) if para_chars else 200,
            "target_total_chars": round(sum(totals) / len(totals)),
            "target_images": round(sum(imgs) / len(imgs)),
            "uses_table": any(b["type"] == "table" for s in samples for b in s.blocks),
            "uses_hr": any(b["type"] == "hr" for s in samples for b in s.blocks),
            "uses_quote": any(b["type"] == "quote" for s in samples for b in s.blocks),
            "opening_samples": [s.opening() for s in samples],
            "closing_samples": closings[-6:],
            "has_footer_cta": any(CTA_HINT.search(t) for t in closings),
            "has_disclaimer": any(DISCLAIMER_HINT.search(t) for t in closings),
            "block_sequences": [[b["type"] for b in s.blocks][:60] for s in samples],
        },
        "evidence": {k: dict(v.most_common(6)) for k, v in sorted(agg.items())},
    }
    return profile


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="学习历史公众号文章排版")
    ap.add_argument("--url", action="append", default=[], help="公开分享链接，可多次传入")
    ap.add_argument("--html", action="append", default=[], help="本地 HTML 文件，可多次传入")
    ap.add_argument("--out", required=True, help="输出 style_profile.json 路径")
    ap.add_argument("--markdown", help="同时输出人读版规范 md")
    args = ap.parse_args(argv)

    if not args.url and not args.html:
        ap.error("至少提供一个 --url 或 --html")

    samples: list[Sample] = []
    errors: list[dict[str, str]] = []
    for u in args.url:
        try:
            samples.append(Sample(u, fetch(u)))
        except Exception as exc:  # noqa: BLE001
            errors.append({"source": u, "error": str(exc)})
    for p in args.html:
        try:
            samples.append(Sample(p, Path(p).read_text(encoding="utf-8", errors="ignore")))
        except Exception as exc:  # noqa: BLE001
            errors.append({"source": p, "error": str(exc)})

    if not samples:
        print(json.dumps({"status": "failed", "errors": errors}, ensure_ascii=False, indent=2))
        return 2

    profile = build_profile(samples)
    profile["errors"] = errors
    out = Path(args.out).expanduser()
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(profile, ensure_ascii=False, indent=2), encoding="utf-8")

    if args.markdown:
        md = Path(args.markdown).expanduser()
        md.parent.mkdir(parents=True, exist_ok=True)
        md.write_text(render_markdown(profile), encoding="utf-8")

    print(
        json.dumps(
            {
                "status": "ok",
                "samples": len(samples),
                "errors": errors,
                "out": str(out),
                "accent_color": profile["accent_color"],
                "heading_pattern": profile["structure"]["heading_pattern"],
                "target_total_chars": profile["structure"]["target_total_chars"],
                "target_images": profile["structure"]["target_images"],
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


def render_markdown(profile: dict[str, Any]) -> str:
    st = profile["structure"]
    lines = [
        "# 本号排版规范（自动学习结果）",
        "",
        f"- 学习样本：{len(profile.get('learned_from', []))} 篇",
        f"- 主色：`{profile['accent_color']}`",
        f"- 小标题形态：`{st['heading_pattern']}`（分布 {st['heading_pattern_counts']}）",
        f"- 目标正文字数：约 {st['target_total_chars']} 字",
        f"- 目标配图数：约 {st['target_images']} 张",
        f"- 段落长度：中位 {st['median_paragraph_chars']} 字，上限 {st['max_paragraph_chars']} 字",
        f"- 使用表格：{st['uses_table']}；使用分割线：{st['uses_hr']}；使用引用块：{st['uses_quote']}",
        f"- 文末含引导语：{st['has_footer_cta']}；文末含数据/免责说明：{st['has_disclaimer']}",
        "",
        "## CSS",
        "```json",
        json.dumps(profile["css"], ensure_ascii=False, indent=2),
        "```",
        "",
        "## 小标题样例",
    ]
    lines += [f"- {h}" for h in st["heading_samples"][:12]]
    lines += ["", "## 开头样例"] + [f"- {t}" for t in st["opening_samples"]]
    lines += ["", "## 结尾样例"] + [f"- {t}" for t in st["closing_samples"]]
    return "\n".join(lines) + "\n"


if __name__ == "__main__":
    raise SystemExit(main())
