#!/usr/bin/env python3
"""从一篇历史文章里把排版组件整段抠出来，做成占位符模板。

适用于用秀米/135 一类模板排版的号（本号即是）：外层渐变容器 + 白卡标题区 +
「圆圈编号 + 章节名」组件 + 白卡正文区 + 固定文末。这类排版无法用 CSS 规则泛化出来，
只能原样复刻，所以这里做的是模板抽取，不是样式统计。

用法:
  extract_template.py --url https://mp.weixin.qq.com/s/xxx \
      --out references/template.json [--outline-out references/outline.json]
"""
from __future__ import annotations

import argparse
import copy
import json
import re
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).parent))
from learn_style import UA, content_root, fetch, text_of  # noqa: E402

try:
    from bs4 import BeautifulSoup
except ImportError:  # pragma: no cover
    sys.exit("缺少 beautifulsoup4")

MARKER_RX = re.compile(r"width:\s*40px;\s*height:\s*40px")
OPEN_TAG_RX = re.compile(r"<section[^>]*>")
POS_COLOR = "rgb(95, 156, 239)"
NEG_COLOR = "rgb(249, 110, 87)"


def is_spacer(node) -> bool:
    return node.name == "p" and not text_of(node) and node.find("br") is not None


def leaf_spans(node):
    return node.find_all("span", attrs={"leaf": ""})


def replace_leaf(node, old_text: str, placeholder: str) -> bool:
    """把 span[leaf] 里等于 old_text 的文本换成占位符。"""
    for sp in leaf_spans(node):
        if text_of(sp) == old_text:
            sp.string = placeholder
            return True
    return False


def first_open_tags(html: str, n: int) -> str:
    out, pos = [], 0
    for _ in range(n):
        m = OPEN_TAG_RX.search(html, pos)
        if not m:
            break
        out.append(m.group(0))
        pos = m.end()
    return "".join(out)


def extract(url: str) -> tuple[dict[str, Any], dict[str, Any]]:
    html = fetch(url)
    soup = BeautifulSoup(html, "lxml")
    root = content_root(soup)
    title_node = soup.select_one("#activity-name, h1.rich_media_title, h1")
    full_title = text_of(title_node) if title_node else ""
    acct_node = soup.select_one("#js_name, .rich_media_meta_nickname")
    account = text_of(acct_node) if acct_node else ""
    # 「跑鞋篇——Nike Zoom Fly 6」→ 栏目 / 鞋名
    column, _, shoe = full_title.partition("——")
    shoe = shoe.strip() or full_title
    column = column.strip()

    elems = [c for c in root.children if getattr(c, "name", None)]
    outer = next((e for e in elems if e.name == "section"), None)
    if outer is None:
        raise RuntimeError("找不到最外层 section 容器")
    kids = [c for c in outer.children if getattr(c, "name", None)]

    tpl: dict[str, Any] = {
        "schema": 1,
        "kind": "component_template",
        "source_url": url,
        "account": account,
        "column": column,
        "colors": {"accent": "rgb(31, 146, 117)", "positive": POS_COLOR, "negative": NEG_COLOR},
    }

    m = OPEN_TAG_RX.match(str(outer))
    tpl["wrapper_open"] = m.group(0) if m else "<section>"
    tpl["wrapper_close"] = "</section>"

    spacer = next((c for c in kids if is_spacer(c)), None)
    tpl["spacer"] = str(spacer) if spacer else ""

    # 标题区
    header = next((c for c in kids if "font-size: 24px" in str(c)), None)
    if header is None:
        raise RuntimeError("找不到标题区组件")
    h = copy.copy(BeautifulSoup(str(header), "lxml").find("section"))
    if not replace_leaf(h, shoe, "{{SHOE_NAME}}"):
        raise RuntimeError(f"标题区里找不到鞋名 {shoe!r}")
    replace_leaf(h, account.replace("RDFZ", "").strip() or account, "{{ACCOUNT}}")
    replace_leaf(h, account, "{{ACCOUNT}}")
    tpl["header"] = str(h)

    # 编号+章节名组件
    marker_idx = [i for i, c in enumerate(kids) if MARKER_RX.search(str(c))]
    if not marker_idx:
        raise RuntimeError("找不到圆圈编号组件")
    mk = BeautifulSoup(str(kids[marker_idx[0]]), "lxml").find("section")
    spans = [text_of(s) for s in leaf_spans(mk)]
    num_text = next((t for t in spans if re.fullmatch(r"\d{2}", t)), None)
    title_text = next((t for t in spans if t and t != num_text), None)
    if not num_text or not title_text:
        raise RuntimeError(f"编号组件解析失败: {spans}")
    replace_leaf(mk, num_text, "{{NUM}}")
    replace_leaf(mk, title_text, "{{SECTION_TITLE}}")
    tpl["marker"] = str(mk)

    # 正文容器：编号组件的下一个兄弟
    bodies = []
    for i in marker_idx:
        cand = kids[i + 1] if i + 1 < len(kids) else None
        if cand is not None and cand.name == "section" and not MARKER_RX.search(str(cand)):
            bodies.append(cand)
    if not bodies:
        raise RuntimeError("找不到正文容器")
    body = bodies[0]
    tpl["body_open"] = first_open_tags(str(body), 2)
    tpl["body_close"] = "</section></section>"

    # 正文内部元素：跨所有小节找（第 01 节通常只有字段，没有子标题）
    cards = [b.find("section") or b for b in bodies]

    def find_in_cards(fn):
        for c in cards:
            hit = fn(c)
            if hit is not None:
                return c, hit
        return None, None

    card, sub_p = find_in_cards(
        lambda c: next(
            (
                p
                for p in c.find_all("p")
                if p.find(["strong", "b"]) and text_of(p) and "text-indent" not in (p.get("style") or "")
            ),
            None,
        )
    )
    if sub_p is None:
        raise RuntimeError("找不到子标题写法")
    s2 = BeautifulSoup(str(sub_p), "lxml").find("p")
    replace_leaf(s2, text_of(sub_p), "{{TEXT}}")
    tpl["sub_heading"] = str(s2)

    # 子标题真身：包含装饰图标 + 绿色文字的整块 flex 组件（秀米组件，不能拆）
    _deco_urls = [i.get("data-src") or "" for i in root.find_all("img")]
    from collections import Counter as _C2

    _dc = _C2([u for u in _deco_urls if u])
    _deco = _dc.most_common(1)[0][0] if _dc else ""
    composite = None
    if _deco:
        cands = []
        for b in bodies:
            for sec in b.find_all("section"):
                if not sec.find("img", attrs={"data-src": _deco}):
                    continue
                t = text_of(sec)
                if t and len(t) <= 24 and sec.find(["strong", "b"]):
                    cands.append((len(str(sec)), sec, t))
        if cands:
            cands.sort(key=lambda x: x[0])
            _, sec, t = cands[0]
            comp = BeautifulSoup(str(sec), "lxml").find("section")
            if replace_leaf(comp, t, "{{TEXT}}"):
                composite = str(comp)
    if composite:
        tpl["sub_heading"] = composite
        tpl["sub_heading_kind"] = "composite_icon_title"

    _, para = find_in_cards(
        lambda c: next(
            (p for p in c.find_all("p") if "text-indent" in (p.get("style") or "") and text_of(p)), None
        )
    )
    if para is None:
        raise RuntimeError("找不到正文段落写法")
    pstyle = para.get("style")
    tpl["paragraph"] = f'<p style="{pstyle}">{{{{CONTENT}}}}</p>'
    tpl["plain_span"] = '<span leaf="">{{TEXT}}</span>'
    # 正文段落外层的「文字容器」：决定对齐、字号、颜色、行高、字距。漏了它段落会继承外层居中
    wrap = para.parent
    if wrap is not None and wrap.name == "section":
        m2 = OPEN_TAG_RX.match(str(wrap))
        if m2:
            tpl["text_wrap_open"] = m2.group(0)
            tpl["text_wrap_close"] = "</section>"


    # 图片：直接包住 img 的 section，连同其外层一层
    img_card, img = find_in_cards(lambda c: c.find("img"))
    if img is None:
        raise RuntimeError("找不到图片写法")
    inner = img.parent
    outer_img = inner.parent if inner.parent is not img_card else inner
    img_html = str(outer_img)
    img_html = re.sub(r'data-src="[^"]*"', 'data-src="{{URL}}" src="{{URL}}"', img_html)
    # 逐图专属属性（比例、宽高、AI 标记）去掉，做成通用模板
    for attr in ("data-aistatus", "data-ratio", "data-w", "data-s", "data-croporisrc", "data-cropx1",
                 "data-cropx2", "data-cropy1", "data-cropy2", "data-imgfileid", "data-fileid"):
        img_html = re.sub(rf'\s{attr}="[^"]*"', "", img_html)
    if 'width="100%"' not in img_html:
        img_html = img_html.replace("<img ", '<img width="100%" ', 1)
    tpl["image"] = img_html

    # 行内强调
    def highlight(color: str) -> str:
        _, el = find_in_cards(lambda c: c.find("span", style=re.compile(re.escape(color))))
        if el is None:
            return f'<span style="color: {color};box-sizing: border-box;"><span leaf="">{{{{TEXT}}}}</span></span>'
        h2 = BeautifulSoup(str(el), "lxml").find("span")
        inner_leaf = h2.find("span", attrs={"leaf": ""})
        if inner_leaf is not None:
            inner_leaf.string = "{{TEXT}}"
        return str(h2)

    tpl["highlight_positive"] = highlight(POS_COLOR)
    tpl["highlight_negative"] = highlight(NEG_COLOR)

    # 装饰图：正文里重复次数最多的那张（本号用它做子标题前的分隔条）
    from collections import Counter as _C

    _urls = [i.get("data-src") or i.get("src") or "" for i in root.find_all("img")]
    _cnt = _C([u for u in _urls if u])
    tpl["deco_image_url"] = ""
    tpl["deco_before_sub"] = False
    if _cnt:
        _url, _n = _cnt.most_common(1)[0]
        if _n >= 3:
            tpl["deco_image_url"] = _url
            # 校验：是否每个子标题前都有一张装饰图
            _subs = _decos = 0
            for _b in bodies:
                for _el in _b.find_all(["p", "img"]):
                    if _el.name == "img":
                        if (_el.get("data-src") or "") == _url:
                            _decos += 1
                    else:
                        _sts = _el.find_all(["strong", "b"])
                        _t = text_of(_el)
                        if (
                            _sts
                            and _t
                            and len(_t) <= 24
                            and re.sub(r"\s+", "", "".join(text_of(x) for x in _sts))
                            == re.sub(r"\s+", "", _t)
                        ):
                            _subs += 1
            tpl["deco_before_sub"] = False  # 装饰图标已包含在 sub_heading 组件内
            tpl["deco_count"] = _decos
            tpl["sub_count"] = _subs

    # 文末：最后两个不含编号/图片的 section
    tail = [c for c in kids[marker_idx[-1] + 1 :] if c.name == "section" and not c.find("img")]
    foot = [c for c in tail if re.search(r"(审核|原创测评|发布日期|测评人)", text_of(c))]
    footer_html = []
    for f in foot:
        fh = BeautifulSoup(str(f), "lxml").find("section")
        for sp in leaf_spans(fh):
            t = text_of(sp)
            for label, ph in (
                ("测评人：", "{{TESTER}}"),
                ("编辑：", "{{EDITOR}}"),
                ("审核：", "{{REVIEWERS}}"),
                ("发布日期：", "{{DATE}}"),
            ):
                if t.startswith(label):
                    sp.string = label + ph
        footer_html.append(str(fh))
    tpl["footer"] = footer_html
    if not footer_html:
        raise RuntimeError("找不到文末固定块")

    # 骨架
    outline = {
        "column": column,
        "shoe": shoe,
        "sections": [],
        "opening_fields": [],
        "footer_defaults": {},
    }
    for i in marker_idx:
        mkn = kids[i]
        spans = [text_of(s) for s in leaf_spans(mkn) if text_of(s)]
        num = next((t for t in spans if re.fullmatch(r"\d{2}", t)), "")
        name = next((t for t in spans if t != num), "")
        subs: list[str] = []
        nxt = kids[i + 1] if i + 1 < len(kids) else None
        if nxt is not None and not MARKER_RX.search(str(nxt)):
            for p in nxt.find_all("p"):
                sts = p.find_all(["strong", "b"])
                t = text_of(p)
                if not sts or not t or len(t) > 24:
                    continue
                joined = "".join(text_of(s) for s in sts)
                if re.sub(r"\s+", "", joined) == re.sub(r"\s+", "", t):
                    subs.append(t)
        outline["sections"].append({"num": num, "title": name, "subs": subs})
    deco_url = tpl.get("deco_image_url") or ""
    for si, i in enumerate(marker_idx):
        nxt = kids[i + 1] if i + 1 < len(kids) else None
        photos = 0
        if nxt is not None and not MARKER_RX.search(str(nxt)):
            for im in nxt.find_all("img"):
                if (im.get("data-src") or "") != deco_url:
                    photos += 1
        outline["sections"][si]["photos"] = photos
    outline["deco_image_url"] = deco_url
    outline["deco_before_sub"] = tpl.get("deco_before_sub", False)
    outline["total_photos"] = sum(s["photos"] for s in outline["sections"])

    body0 = kids[marker_idx[0] + 1] if marker_idx[0] + 1 < len(kids) else None
    if body0 is not None:
        for p in body0.find_all("p"):
            t = text_of(p)
            if "：" in t and len(t) < 60:
                outline["opening_fields"].append(t)
    for f in foot:
        for sp in leaf_spans(f):
            t = text_of(sp)
            if t.startswith("审核："):
                outline["footer_defaults"]["reviewers"] = t[len("审核：") :]
            elif t.startswith("编辑："):
                outline["footer_defaults"]["editor"] = t[len("编辑：") :]
            elif t.startswith("测评人："):
                outline["footer_defaults"]["tester"] = t[len("测评人：") :]
            elif t.startswith("注："):
                outline["footer_defaults"]["note"] = t
    return tpl, outline


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="抽取公众号排版组件模板")
    ap.add_argument("--url", required=True, help="参考文章的公开分享链接")
    ap.add_argument("--out", required=True)
    ap.add_argument("--outline-out")
    args = ap.parse_args(argv)

    try:
        tpl, outline = extract(args.url)
    except Exception as exc:  # noqa: BLE001
        print(json.dumps({"status": "failed", "error": str(exc)}, ensure_ascii=False, indent=2))
        return 2

    out = Path(args.out).expanduser()
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(tpl, ensure_ascii=False, indent=2), encoding="utf-8")
    if args.outline_out:
        o = Path(args.outline_out).expanduser()
        o.parent.mkdir(parents=True, exist_ok=True)
        o.write_text(json.dumps(outline, ensure_ascii=False, indent=2), encoding="utf-8")

    print(
        json.dumps(
            {
                "status": "ok",
                "out": str(out),
                "outline_out": args.outline_out,
                "account": tpl["account"],
                "column": tpl["column"],
                "components": [k for k in tpl if k not in ("schema", "kind", "source_url", "colors")],
                "sections": [f'{s["num"]} {s["title"]}' for s in outline["sections"]],
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
