#!/usr/bin/env python3
"""文风与格式检查：把「步界社」的写作规矩做成机械校验，写完必跑。

检查项（全部来自用户历史文章与明确要求）：
  · 禁用实验室缩写 SA / BR / AC / Nm，禁用 v41 这类写法
  · 不写产品改进建议、不引导读者去买别的鞋
  · 行内标色语义：**…** 只标优点，~~…~~ 只标缺点；密度对齐历史文章
  · 型号名要带品牌名
  · 开篇 5 字段齐全且顺序正确
  · 文末不出现「审核」；评分维度按栏目区分（跑鞋 5 项 X/10，篮球鞋 7 项 X 分）
  · 图片位 4 个；正文里提到的优缺点要进优缺点列表
  · 不写绝对化表述

用法:
  style_lint.py --article article.json [--outline references/outline_running.json]
退出码：0 通过（可能有 warning） / 4 有 blocking
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any

JARGON = {
    r"\bSA\b": "实验室缩写 SA",
    r"\bBR\b": "实验室缩写 BR",
    r"\bAC\b": "实验室缩写 AC",
    r"\bNm\b": "实验室缩写 Nm",
    r"\bv\d{2}\b": "v41 这类写法，应写「上一代」",
}
EXTERNAL_RX = re.compile(
    r"(RunRepeat|实验室|评测机构|测评机构|数据来源|第三方(测试|数据)|官方数据显示|"
    r"外媒|榜单|据[^。]{0,8}(测试|测评|实测数据))")
PEER_RX = re.compile(
    r"(同价位|同类|同级|同等价格|同段位|均值|平均值|平均水平|比同|在这个价位|这个价位里|"
    r"比大多数|多数竞品|竞品里)")
ADVICE_RX = re.compile(
    r"(应该去看|建议.{0,6}(换|改用|选)|可以看看[^。]{0,12}(鞋|款)|还有.{0,4}空间|"
    r"如果.{0,10}(会更好|就更好)|需要改进|有待改进|减薄|下一代)"
)
ABSOLUTE_RX = re.compile(r"(最强|第一|唯一|绝对|必买|稳赚|无脑买|100%|完胜|吊打)")
POS_RX = re.compile(r"\*\*(.+?)\*\*")
NEG_RX = re.compile(r"~~(.+?)~~")
# 标色语义判别词
# 「一般」有歧义：「表现一般」是负面，「比一般跑鞋…」是"通常"的意思，只认前者
NEG_WORDS = re.compile(r"(不足|偏薄|偏重|偏窄|衰减|不如|短板|不算|吃力|发累|挤脚|偏沉|"
                       r"不耐磨|变差|偏弱|缺乏|有问题|闷热|打滑|拖沓|撑不住|不轻快|"
                       r"表现一般|性能一般|比较一般|都一般|只是一般|一般$)")
POS_WORDS = re.compile(r"(出色|优秀|扎实|到位|稳固|稳定|省劲|舒适|好过|提升|友好|轻松|够用|"
                       r"清晰|规整|不错|明显好)")
# 否定式：「没有打滑」「不累脚」这类是优点，不能按负面词判
NEGATION_RX = re.compile(r"(没有|不会|不再|未出现|无|不)\s*([\u4e00-\u9fff]{1,4})")


def strip_negation(t: str) -> str:
    """把否定式整体去掉，避免「没有打滑」被误判成负面。"""
    return NEGATION_RX.sub(" ", t)
MODELS = ["Pegasus", "Vomero", "Structure", "Novablast", "Superblast", "Bondi",
          "LeBron", "KD", "Ja", "Jordan", "Zoom Fly", "Adizero", "Mach"]
BRANDS = ["Nike", "ASICS", "HOKA", "adidas", "Adidas", "New Balance", "李宁", "安踏",
          "361", "特步", "Air Jordan", "Brooks", "Saucony", "PUMA"]
FIELDS = ["测评鞋款", "产品定位", "官方发售价", "二级平台价格", "实测重量"]


def texts(a: dict[str, Any]) -> list[tuple[str, str]]:
    out = []
    for s in a.get("sections", []):
        tag = f"{s.get('num')}{s.get('title')}"
        for b in s.get("blocks", []):
            if b.get("text"):
                out.append((tag, b["text"]))
            for x in b.get("items", []):
                out.append((tag, str(x)))
    return out


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="文风与格式检查")
    ap.add_argument("--article", required=True)
    ap.add_argument("--outline")
    args = ap.parse_args(argv)

    a = json.loads(Path(args.article).expanduser().read_text(encoding="utf-8"))
    blocking: list[str] = []
    warn: list[str] = []
    tx = texts(a)
    body = "\n".join(t for _, t in tx)

    # 1 术语
    for rx, why in JARGON.items():
        for loc, t in tx:
            if re.search(rx, t):
                blocking.append(f"[{loc}] {why}：{t[:50]}")
                break

    # 2 建议类 / 绝对化
    for loc, t in tx:
        if ADVICE_RX.search(t):
            blocking.append(f"[{loc}] 出现改进建议或引导买别的鞋：{t[:50]}")
        if "「" in t or "」" in t:
            blocking.append(f"[{loc}] 正文不要用「」：{t[:44]}")
        if PEER_RX.search(t):
            blocking.append(f"[{loc}] 出现同价位/同类横向比较，只说这双鞋本身：{t[:44]}")
        if EXTERNAL_RX.search(t):
            blocking.append(f"[{loc}] 正文提到了外部机构/网站，应删掉直接给结论：{t[:44]}")
        if ABSOLUTE_RX.search(t):
            warn.append(f"[{loc}] 绝对化表述：{t[:50]}")

    # 3 标色语义与密度
    pos = POS_RX.findall(body)
    neg = NEG_RX.findall(body)
    if not 18 <= len(pos) <= 42:
        warn.append(f"蓝色（优点）标注 {len(pos)} 处，历史约 30 处")
    if not 6 <= len(neg) <= 18:
        warn.append(f"橙色（缺点）标注 {len(neg)} 处，历史约 10 处")
    for p in pos:
        q = strip_negation(p)
        if NEG_WORDS.search(q) and not POS_WORDS.search(q):
            blocking.append(f"标蓝的是负面表述，应改成橙色：「{p[:28]}」")
    for n in neg:
        q = strip_negation(n)
        if POS_WORDS.search(q) and not NEG_WORDS.search(q):
            blocking.append(f"标橙的是正面表述，应改成蓝色：「{n[:28]}」")

    # 4 型号名要带品牌
    for m in MODELS:
        for loc, t in tx:
            for mm in re.finditer(re.escape(m), t):
                head = t[max(0, mm.start() - 18):mm.start()]
                if not any(b in head for b in BRANDS):
                    warn.append(f"[{loc}] 「{m}」前面没有品牌名：…{head[-14:]}{m}")
                break

    # 4.5 优缺点区域不得标色（历史文章这两段没有彩色字）
    for sec in a.get("sections", []):
        mode = None
        for b in sec.get("blocks", []):
            if b.get("type") == "sub":
                mode = b.get("text")
                continue
            if mode in ("优点", "缺点") and b.get("text"):
                if POS_RX.search(b["text"]) or NEG_RX.search(b["text"]):
                    blocking.append(f"[{sec.get('num')}{mode}] 这一段不应标颜色："
                                    f"{b['text'][:40]}")

    # 5 开篇 5 字段
    first = (a.get("sections") or [{}])[0]
    got = [str(x) for b in first.get("blocks", []) if b.get("type") == "fields"
           for x in b.get("items", [])]
    labels = [g.split("：")[0] for g in got]
    if labels != FIELDS:
        blocking.append(f"开篇字段是 {labels}，应为 {FIELDS}")
    for g in got:
        if not g.startswith("二级平台价格") and re.search(r"(待补|待定|TODO|待填)", g):
            blocking.append(f"开篇字段没填完：{g}")
        if g.startswith("二级平台价格") and not re.search(r"(待补|¥\d+～¥\d+)", g):
            blocking.append(f"二级平台价格写法不对：{g}")

    # 6 文末
    f = a.get("footer", {})
    if f.get("reviewers"):
        blocking.append("文末不应出现「审核」（reviewers 必须留空）")
    if not f.get("date"):
        warn.append("文末缺发布日期")

    # 7 评分维度
    column = a.get("column", "")
    scores = [str(x) for s in a.get("sections", []) for b in s.get("blocks", [])
              if b.get("type") == "scores" for x in b.get("items", [])]
    if scores:
        n = len(scores) - 1  # 去掉综合得分
        if "跑鞋" in column:
            if n != 5:
                blocking.append(f"跑鞋篇评分应 5 项 + 综合，实际 {n} 项")
            if not all("/10" in s for s in scores):
                blocking.append("跑鞋篇评分应写成 X/10")
        elif "球鞋" in column or "篮球" in column:
            if n != 7:
                blocking.append(f"篮球鞋篇评分应 7 项 + 综合，实际 {n} 项")
            if not all("分" in s for s in scores):
                blocking.append("篮球鞋篇评分应写成 X 分")
    else:
        blocking.append("缺少评分块")

    # 8 图片位
    imgs = sum(1 for s in a.get("sections", []) for b in s.get("blocks", [])
               if b.get("type") == "img")
    if imgs != 4:
        blocking.append(f"图片位 {imgs} 个，应为 4 个")

    # 9 骨架
    if args.outline and Path(args.outline).exists():
        o = json.loads(Path(args.outline).read_text(encoding="utf-8"))
        want = o.get("sections", [])
        got_s = a.get("sections", [])
        for i, w in enumerate(want):
            if i >= len(got_s):
                blocking.append(f"缺少章节 {w['num']} {w['title']}")
                continue
            g = got_s[i]
            if str(g.get("num")) != w["num"] or g.get("title") != w["title"]:
                blocking.append(f"第 {i+1} 节是「{g.get('num')} {g.get('title')}」，"
                                f"应为「{w['num']} {w['title']}」")
            subs = [b["text"] for b in g.get("blocks", []) if b.get("type") == "sub"]
            if subs != w["subs"]:
                blocking.append(f"{w['num']} 子标题 {subs}，应为 {w['subs']}")

    print(json.dumps({
        "status": "failed" if blocking else ("passed_with_warnings" if warn else "passed"),
        "blocking_count": len(blocking), "warning_count": len(warn),
        "blocking": blocking, "warnings": warn,
        "highlight": {"positive": len(pos), "negative": len(neg)},
    }, ensure_ascii=False, indent=2))
    return 4 if blocking else 0


if __name__ == "__main__":
    sys.exit(main())
