#!/usr/bin/env python3
"""用 extract_template.py 抠出的组件模板，把结构化稿件渲染成 1:1 复刻历史排版的 HTML。

与 render_article.py 的区别：那个是按 CSS 规则泛化生成（适合普通号），
这个是把历史文章的组件原样套用（适合秀米/135 模板号，本号即是）。

用法:
  render_template.py --article article.json --template references/template_rdfz.json \
      --outline references/outline_running.json --out article.html [--strict]
"""
from __future__ import annotations

import argparse
import html
import json
import re
import sys

from bs4 import BeautifulSoup
from pathlib import Path
from typing import Any

POS_RX = re.compile(r"\*\*(.+?)\*\*")
NEG_RX = re.compile(r"~~(.+?)~~")
TOKEN_RX = re.compile(r"(\*\*.+?\*\*|~~.+?~~)")


def esc(t: str) -> str:
    return html.escape(t, quote=False)


class TemplateRenderer:
    def __init__(self, tpl: dict[str, Any]):
        self.t = tpl
        self.warnings: list[str] = []
        self.dropped_footer_lines: list[str] = []

    def fill(self, key: str, **kw: str) -> str:
        out = self.t[key]
        for k, v in kw.items():
            out = out.replace(f"{{{{{k}}}}}", v)
        left = re.findall(r"\{\{(\w+)\}\}", out)
        if left:
            self.warnings.append(f"模板 {key} 还有未替换的占位符 {left}")
        return out

    # -- 行内 ------------------------------------------------------------
    def inline(self, text: str) -> str:
        """**正面** → 蓝色强调；~~短板~~ → 橙色强调；其余走普通 span。"""
        parts: list[str] = []
        for seg in TOKEN_RX.split(text):
            if not seg:
                continue
            m = POS_RX.fullmatch(seg)
            if m:
                parts.append(self.fill("highlight_positive", TEXT=esc(m.group(1))))
                continue
            m = NEG_RX.fullmatch(seg)
            if m:
                parts.append(self.fill("highlight_negative", TEXT=esc(m.group(1))))
                continue
            parts.append(self.fill("plain_span", TEXT=esc(seg)))
        return "".join(parts)

    # -- 块 --------------------------------------------------------------
    def block(self, b: dict[str, Any]) -> str:
        t = b.get("type")
        if t == "p":
            return self.fill("paragraph", CONTENT=self.inline(b["text"]))
        if t == "sub":
            return self.fill("sub_heading", TEXT=esc(b["text"]))
        if t == "img":
            url = b.get("url", "")
            if not url.startswith("http"):
                self.warnings.append(f"图片不是 http 地址（{url}），公众号正文无法显示")
            return self.fill("image", URL=esc(url))
        if t in ("fields", "scores", "lines"):
            return "".join(
                self.fill("paragraph", CONTENT=self.inline(str(x))) for x in b.get("items", [])
            )
        if t == "raw":
            return b.get("html", "")
        self.warnings.append(f"未知块类型 {t!r}，已跳过")
        return ""

    def deco(self) -> str:
        """子标题前的固定装饰条：本号每个子标题前都有一张，用账号既有素材，不重新上传。"""
        url = self.t.get("deco_image_url", "")
        if not url:
            return ""
        return self.fill("image", URL=url)

    TEXTY = ("p", "fields", "lines", "scores")

    def section(self, s: dict[str, Any]) -> str:
        """连续的文字块要包在「文字容器」里，否则会继承外层的居中并丢掉字号/颜色/行高。"""
        wo = self.t.get("text_wrap_open", "")
        wc = self.t.get("text_wrap_close", "")
        auto = bool(self.t.get("deco_before_sub")) and self.t.get("deco_image_url") \
            and self.t.get("sub_heading_kind") != "composite_icon_title"
        pieces: list[str] = []
        buf: list[str] = []

        def flush() -> None:
            if not buf:
                return
            pieces.append((wo + "".join(buf) + wc) if wo else "".join(buf))
            buf.clear()

        for b in s.get("blocks", []):
            t = b.get("type")
            if t in self.TEXTY:
                buf.append(self.block(b))
                continue
            flush()
            if auto and t == "sub":
                pieces.append(self.deco())
            pieces.append(self.block(b))
        flush()
        inner = "".join(pieces)
        return (
            self.fill("marker", NUM=esc(str(s.get("num", ""))), SECTION_TITLE=esc(s.get("title", "")))
            + self.t["body_open"]
            + inner
            + self.t["body_close"]
        )

    def footer_fragment(self, frag: str, vals: dict[str, str]) -> str:
        """值为空的占位符，整行删掉（例如不写审核就不出现「审核：」这一行）。"""
        empty = {k for k, v in vals.items() if not v}
        if empty:
            soup = BeautifulSoup(frag, "html.parser")
            for node in list(soup.find_all("p")):
                txt = node.decode()
                if any(f"{{{{{k}}}}}" in txt for k in empty):
                    node.decompose()
                    self.dropped_footer_lines.append(
                        next(k for k in empty if f"{{{{{k}}}}}" in txt)
                    )
            frag = str(soup)
        for k, v in vals.items():
            frag = frag.replace(f"{{{{{k}}}}}", v)
        left = re.findall(r"\{\{(\w+)\}\}", frag)
        if left:
            self.warnings.append(f"文末还有未替换的占位符 {left}")
        return frag

    def render(self, art: dict[str, Any]) -> str:
        spacer = self.t.get("spacer", "")
        shoe = art.get("shoe") or art.get("title", "")
        account = art.get("account") or self.t.get("account", "")
        parts = [
            self.t["wrapper_open"],
            spacer,
            spacer,
            self.fill("header", SHOE_NAME=esc(shoe), ACCOUNT=esc(account)),
            spacer,
            spacer,
        ]
        for s in art.get("sections", []):
            parts.append(self.section(s))
            parts.append(spacer)

        f = art.get("footer", {})
        vals = {
            "TESTER": esc(f.get("tester", "")),
            "EDITOR": esc(f.get("editor", "")),
            "REVIEWERS": esc(f.get("reviewers", "")),
            "DATE": esc(f.get("date", "")),
        }
        if not vals["DATE"]:
            self.warnings.append("文末缺发布日期")
        for frag in self.t.get("footer", []):
            parts.append(self.footer_fragment(frag, vals))
        parts.append(self.t["wrapper_close"])
        return "".join(parts)


def check_outline(art: dict, outline: dict) -> list[str]:
    warn: list[str] = []
    want = outline.get("sections", [])
    got = art.get("sections", [])
    if len(got) != len(want):
        warn.append(f"章节数 {len(got)}，历史骨架是 {len(want)}")
    for i, w in enumerate(want):
        if i >= len(got):
            warn.append(f"缺少章节 {w['num']} {w['title']}")
            continue
        g = got[i]
        if str(g.get("num")) != w["num"] or g.get("title") != w["title"]:
            warn.append(
                f"第 {i+1} 节是「{g.get('num')} {g.get('title')}」，历史骨架是「{w['num']} {w['title']}」"
            )
        subs_got = [b["text"] for b in g.get("blocks", []) if b.get("type") == "sub"]
        if subs_got != w["subs"]:
            warn.append(f"{w['num']} 子标题 {subs_got}，历史是 {w['subs']}")
    # 开篇字段
    if got:
        fields = [
            x
            for b in got[0].get("blocks", [])
            if b.get("type") == "fields"
            for x in b.get("items", [])
        ]
        want_labels = [f.split("：")[0] for f in outline.get("opening_fields", [])]
        got_labels = [str(f).split("：")[0] for f in fields]
        if got_labels != want_labels:
            warn.append(f"开篇字段 {got_labels}，历史是 {want_labels}")
    # 实拍图方案：历史是 01–04 各 1 张，05/06 无实拍；子标题前的装饰条由渲染器自动插
    for i, w in enumerate(want):
        if i >= len(got) or "photos" not in w:
            continue
        n = sum(1 for b in got[i].get("blocks", []) if b.get("type") == "img")
        if n != w["photos"]:
            warn.append(f"{w['num']} {w['title']} 实拍图 {n} 张，历史是 {w['photos']} 张")
    total = sum(1 for s in got for b in s.get("blocks", []) if b.get("type") == "img")
    if outline.get("total_photos") and total != outline["total_photos"]:
        warn.append(f"实拍图共 {total} 张，历史是 {outline['total_photos']} 张")
    chars = sum(
        len(b.get("text", "")) + sum(len(str(x)) for x in b.get("items", []))
        for s in got
        for b in s.get("blocks", [])
    )
    if not 1200 <= chars <= 3200:
        warn.append(f"正文约 {chars} 字，历史约 2000 字")
    return warn


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="按组件模板渲染公众号 HTML")
    ap.add_argument("--article", required=True)
    ap.add_argument("--template", required=True)
    ap.add_argument("--outline")
    ap.add_argument("--out", required=True)
    ap.add_argument("--strict", action="store_true")
    args = ap.parse_args(argv)

    art = json.loads(Path(args.article).expanduser().read_text(encoding="utf-8"))
    tpl = json.loads(Path(args.template).expanduser().read_text(encoding="utf-8"))

    r = TemplateRenderer(tpl)
    warns: list[str] = []
    if args.outline:
        outline = json.loads(Path(args.outline).expanduser().read_text(encoding="utf-8"))
        warns += check_outline(art, outline)
    out_html = r.render(art)
    warns += r.warnings

    out = Path(args.out).expanduser()
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(out_html, encoding="utf-8")

    report = {
        "status": "ok" if not warns else "ok_with_warnings",
        "out": str(out),
        "bytes": len(out_html.encode("utf-8")),
        "sections": len(art.get("sections", [])),
        "photos": sum(1 for s in art.get("sections", []) for b in s.get("blocks", []) if b.get("type") == "img"),
        "deco_inserted": sum(1 for s in art.get("sections", []) for b in s.get("blocks", []) if b.get("type") == "sub")
        if (tpl.get("deco_before_sub") and tpl.get("deco_image_url"))
        else 0,
        "footer_lines_dropped": r.dropped_footer_lines,
        "warnings": warns,
    }
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 3 if (warns and args.strict) else 0


if __name__ == "__main__":
    sys.exit(main())
