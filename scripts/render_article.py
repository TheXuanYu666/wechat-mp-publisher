#!/usr/bin/env python3
"""把结构化 article.json 渲染成公众号编辑器可直接粘贴的内联样式 HTML。

公众号编辑器只保留 inline style，因此不生成 <style> 标签、不使用 class。

用法:
  render_article.py --article article.json --profile style_profile.json --out article.html
  render_article.py --article article.json --profile p.json --out a.html --strict
"""
from __future__ import annotations

import argparse
import html
import json
import re
import sys
from pathlib import Path
from typing import Any

BLOCK_TYPES = {
    "h2",
    "h3",
    "p",
    "img",
    "quote",
    "hr",
    "list",
    "olist",
    "table",
    "sources",
    "raw",
}


def css(d: dict[str, Any], *, extra: str = "") -> str:
    parts = [f"{k}: {v}" for k, v in d.items() if v not in (None, "", "none") and not k.startswith("_")]
    if extra:
        parts.append(extra.rstrip(";"))
    return "; ".join(parts) + ";"


def esc(t: str) -> str:
    return html.escape(t, quote=False)


INLINE_RX = re.compile(r"\*\*(.+?)\*\*")


def inline(text: str, accent: str) -> str:
    """支持 **加粗**（用主色强调，与公众号常见写法一致）。"""
    out = esc(text)
    return INLINE_RX.sub(
        lambda m: f'<strong style="color: {accent}; font-weight: bold;">{m.group(1)}</strong>',
        out,
    )


class Renderer:
    def __init__(self, profile: dict[str, Any], *, strict: bool = False):
        self.prof = profile
        self.c = profile["css"]
        self.accent = profile.get("accent_color", "#c0392b")
        self.family = profile.get("font_family")
        self.strict = strict
        self.warnings: list[str] = []

    def font(self, base: dict[str, Any]) -> dict[str, Any]:
        d = dict(base)
        if self.family:
            d.setdefault("font-family", self.family)
        return d

    # -- 单块渲染 --------------------------------------------------------
    def h2(self, b: dict) -> str:
        style = self.font(self.c["h2"])
        return f'<p style="{css(style)}">{inline(b["text"], self.accent)}</p>'

    def h3(self, b: dict) -> str:
        style = self.font(self.c["h3"])
        return f'<p style="{css(style)}">{inline(b["text"], self.accent)}</p>'

    def p(self, b: dict) -> str:
        style = self.font(self.c["body"])
        limit = self.p_limit()
        if limit and len(b["text"]) > limit:
            self.warnings.append(
                f"段落 {len(b['text'])} 字超过历史上限 {limit} 字：{b['text'][:24]}…"
            )
        return f'<p style="{css(style)}">{inline(b["text"], self.accent)}</p>'

    def p_limit(self) -> int | None:
        st = self.prof.get("structure", {})
        v = st.get("max_paragraph_chars")
        return int(v * 1.3) if v else None

    def quote(self, b: dict) -> str:
        style = self.font(self.c["quote"])
        return f'<section style="{css(style)}">{inline(b["text"], self.accent)}</section>'

    def hr(self, _b: dict) -> str:
        d = self.c["hr"]
        return (
            f'<p style="{css(d)} border-bottom: none; height: 0; line-height: 0;'
            ' font-size: 0;"><br/></p>'
        )

    def img(self, b: dict) -> str:
        src = b.get("url") or b.get("path") or ""
        if not src:
            self.warnings.append("图片块缺少 url/path")
        if not src.startswith("http"):
            self.warnings.append(
                f"图片 src 不是 http 地址（{src}）：公众号正文只接受已上传到素材库的图片，"
                "请先跑 mp_draft.py --upload-images"
            )
        style = dict(self.c["img"])
        alt = esc(b.get("alt", ""))
        out = [f'<p style="text-align: center; margin: 18px 0 0;">'
               f'<img src="{esc(src)}" alt="{alt}" style="{css(style)}"/></p>']
        if b.get("caption"):
            cap = self.font(self.c["caption"])
            out.append(f'<p style="{css(cap)}">{esc(b["caption"])}</p>')
        return "".join(out)

    def list(self, b: dict, ordered: bool = False) -> str:
        style = self.font(self.c["body"])
        item_style = css(style, extra="margin-bottom: 8px")
        rows = []
        for i, it in enumerate(b.get("items", []), 1):
            marker = f"{i}." if ordered else "·"
            rows.append(
                f'<p style="{item_style}">'
                f'<span style="color: {self.accent}; font-weight: bold;">{marker}</span> '
                f"{inline(str(it), self.accent)}</p>"
            )
        return "".join(rows)

    def olist(self, b: dict) -> str:
        return self.list(b, ordered=True)

    def table(self, b: dict) -> str:
        t = self.c["table"]
        border = t.get("border", "1px solid #e6e6e6")
        base = (
            f'border-collapse: collapse; width: 100%; font-size: {t.get("font-size", "13px")};'
            " table-layout: fixed;"
        )
        cell = f"border: {border}; padding: 7px 6px; word-break: break-all;"
        head_cell = (
            f'{cell} background-color: {t.get("header_bg", "#f5f5f5")};'
            f' color: {t.get("header_color", "#222222")}; font-weight: bold;'
        )
        rows_html = []
        headers = b.get("headers") or []
        if headers:
            rows_html.append(
                "<tr>"
                + "".join(
                    f'<th style="{head_cell} text-align: {"left" if i == 0 else "center"};">{esc(str(h))}</th>'
                    for i, h in enumerate(headers)
                )
                + "</tr>"
            )
        for row in b.get("rows", []):
            rows_html.append(
                "<tr>"
                + "".join(
                    f'<td style="{cell} text-align: {"left" if i == 0 else "center"};">'
                    f"{inline(str(c), self.accent)}</td>"
                    for i, c in enumerate(row)
                )
                + "</tr>"
            )
        out = f'<table style="{base}"><tbody>{"".join(rows_html)}</tbody></table>'
        wrapper = f'<p style="margin: 14px 0;">{out}</p>'
        if b.get("caption"):
            cap = self.font(self.c["caption"])
            wrapper += f'<p style="{css(cap)}">{esc(b["caption"])}</p>'
        return wrapper

    def sources(self, b: dict) -> str:
        """参考资料区：每条都必须有标题+链接。"""
        items = b.get("items", [])
        head = self.font(dict(self.c["h3"]))
        small = self.font(
            {
                "font-size": "12px",
                "color": "#999999",
                "line-height": "1.7",
                "margin-bottom": "6px",
                "word-break": "break-all",
            }
        )
        parts = [f'<p style="{css(head)}">{esc(b.get("title", "数据来源"))}</p>']
        for i, it in enumerate(items, 1):
            title = esc(it.get("title") or it.get("url", ""))
            url = esc(it.get("url", ""))
            date = it.get("date") or it.get("accessed") or ""
            suffix = f"（{esc(date)}）" if date else ""
            parts.append(f'<p style="{css(small)}">[{i}] {title}{suffix} {url}</p>')
        if not items:
            self.warnings.append("sources 块为空：文章不应无数据来源")
        return "".join(parts)

    def raw(self, b: dict) -> str:
        return b.get("html", "")

    # -- 整体 ------------------------------------------------------------
    def render(self, article: dict[str, Any]) -> str:
        blocks = article.get("blocks", [])
        out: list[str] = []
        for b in blocks:
            t = b.get("type")
            if t not in BLOCK_TYPES:
                self.warnings.append(f"未知块类型 {t!r}，已跳过")
                continue
            out.append(getattr(self, t)(b))
        body = "".join(out)
        wrap_style = css(
            self.font(
                {
                    "font-size": self.c["body"].get("font-size", "15px"),
                    "color": self.c["body"].get("color", "#3f3f3f"),
                    "line-height": self.c["body"].get("line-height", "1.75"),
                    "letter-spacing": self.c["body"].get("letter-spacing", "0.5px"),
                }
            )
        )
        return f'<section style="{wrap_style}">{body}</section>'


def check_structure(article: dict, profile: dict) -> list[str]:
    """把渲染前的结构与历史规范对齐，返回提示。"""
    warn: list[str] = []
    st = profile.get("structure", {})
    blocks = article.get("blocks", [])
    text_chars = sum(len(b.get("text", "")) for b in blocks if b.get("type") in ("p", "quote"))
    target = st.get("target_total_chars")
    if target:
        lo, hi = target * 0.6, target * 1.6
        if not lo <= text_chars <= hi:
            warn.append(
                f"正文 {text_chars} 字，历史均值 {target} 字，建议区间 {int(lo)}–{int(hi)} 字"
            )
    imgs = sum(1 for b in blocks if b.get("type") == "img")
    tgt_img = st.get("target_images")
    if tgt_img and imgs < max(1, tgt_img - 2):
        warn.append(f"配图 {imgs} 张，历史均值 {tgt_img} 张，偏少")
    if st.get("uses_table") and not any(b.get("type") == "table" for b in blocks):
        warn.append("历史文章常用表格，本篇没有表格")
    if not any(b.get("type") == "sources" for b in blocks):
        warn.append("缺少 sources 数据来源块")
    pattern = st.get("heading_pattern")
    if pattern and pattern != "plain":
        rx = {
            "numbered_cn": r"^\s*[一二三四五六七八九十]+[、.．]",
            "numbered_ar": r"^\s*\d{1,2}[、.．)）]",
            "bracket": r"^\s*[【\[（(]",
            "emoji": r"^\s*[\U0001F300-\U0001FAFF\u2600-\u27BF]",
            "pipe": r"^\s*[|｜]",
        }.get(pattern)
        if rx:
            bad = [
                b["text"]
                for b in blocks
                if b.get("type") == "h2" and not re.match(rx, b.get("text", ""))
            ]
            if bad:
                warn.append(f"以下小标题不符合历史形态 {pattern}：{bad[:3]}")
    return warn


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="渲染公众号 HTML")
    ap.add_argument("--article", required=True)
    ap.add_argument("--profile", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--strict", action="store_true", help="有告警时以非零码退出")
    args = ap.parse_args(argv)

    article = json.loads(Path(args.article).expanduser().read_text(encoding="utf-8"))
    profile = json.loads(Path(args.profile).expanduser().read_text(encoding="utf-8"))

    r = Renderer(profile, strict=args.strict)
    warns = check_structure(article, profile)
    html_out = r.render(article)
    warns += r.warnings

    out = Path(args.out).expanduser()
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(html_out, encoding="utf-8")

    report = {
        "status": "ok" if not warns else "ok_with_warnings",
        "out": str(out),
        "bytes": len(html_out.encode("utf-8")),
        "title": article.get("title", ""),
        "blocks": len(article.get("blocks", [])),
        "warnings": warns,
    }
    print(json.dumps(report, ensure_ascii=False, indent=2))
    if warns and args.strict:
        return 3
    return 0


if __name__ == "__main__":
    sys.exit(main())
