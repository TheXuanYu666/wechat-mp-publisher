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
# 用于发现未着色的明确评价。重点覆盖“没有多余堆料、不生硬、不拖脚”等否定式优点，
# 以及包裹、支撑、做工、抓地、耐磨等高置信度评价；只在 02–05 测评正文中使用。
CLEAR_POSITIVE_RX = re.compile(
    r"((?:没有|不会|不再|未出现|无)[^，。；]{0,10}(?:多余堆料|突兀(?:的)?硬边|打滑|乱晃|"
    r"拖脚|拖重量|压迫|磨脚|生硬|松散)|不(?:生硬|拖脚|拖重量|乱晃|费劲)|"
    r"(?:压力分布|受力)(?:很|更|比较|较)?均匀|(?:包裹|活动|转换|过渡)(?:很|更|比较|较)?自然|"
    r"(?:处理|接合|做工)[^，。；]{0,10}(?:干净|细致)|(?:扎实|稳定|可靠|充足)的?(?:承托|支撑|保护|锁定)|"
    r"(?:抓地|制动)(?:很|更|比较|较)?(?:直接|可靠|稳定)|(?:完成度|保护性|耐用感)[^，。；]{0,6}(?:高|不错|出色)|"
    r"(?:抗磨|耐磨)[^，。；]{0,8}(?:较好|扎实|耐用))"
)
CLEAR_NEGATIVE_RX = re.compile(
    r"((?:鞋舌|鞋头|鞋楦|鞋身)[^，。；]{0,8}(?:偏薄|偏重|偏窄)|"
    r"(?:通风|透气|填充|反馈|利落感|灵巧)[^，。；]{0,8}(?:不够|不足|有限|偏少|不算充分)|"
    r"容易积热|轻微空量感|不够锐利|不够灵巧)"
)
SOURCE_META_RX = re.compile(
    r"(现有资料|公开资料|资料不足|检索|搜索|查不到|没查到|没有查到|不硬写数字|"
    r"无法给出(?:可靠的)?(?:具体)?数据|可以确认的是)"
)
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
    """Extract all text content from article for linting.
    
    Supports both old structure (sections[].blocks[]) and new structure (blocks[].content[]).
    """
    out = []
    # Try new structure first (blocks[])
    if "blocks" in a and not "sections" in a:
        for s in a.get("blocks", []):
            if s.get("type") != "section":
                continue
            tag = f"{s.get('heading')}{s.get('title')}"
            for b in s.get("content", []):
                if b.get("text"):
                    out.append((tag, b["text"]))
                if b.get("items"):
                    for x in b["items"]:
                        out.append((tag, str(x)))
            # Also check subsections
            for sub in s.get("subsections", []):
                for b in sub.get("content", []):
                    if b.get("text"):
                        out.append((tag, b["text"]))
                    if b.get("items"):
                        for x in b["items"]:
                            out.append((tag, str(x)))
    else:
        # Old structure (sections[])
        for s in a.get("sections", []):
            tag = f"{s.get('num')}{s.get('title')}"
            for b in s.get("blocks", []):
                if b.get("text"):
                    out.append((tag, b["text"]))
                for x in b.get("items", []):
                    out.append((tag, str(x)))
    return out


def get_sections(a: dict[str, Any]) -> list[dict[str, Any]]:
    """Get sections from article, handling both old and new structure.
    
    Returns normalized sections with: heading/num, title, content/blocks, img (if present).
    """
    if "blocks" in a and not "sections" in a:
        # New structure: extract section blocks
        sections = []
        for s in a.get("blocks", []):
            if s.get("type") == "section":
                # Normalize: heading->num, content->blocks, preserve img
                normalized = {
                    "num": s.get("heading"),
                    "heading": s.get("heading"),
                    "title": s.get("title"),
                    "blocks": s.get("content", []),
                    "content": s.get("content", []),
                    "subsections": s.get("subsections", []),
                }
                if "img" in s:
                    normalized["img"] = s["img"]
                sections.append(normalized)
        return sections
    else:
        # Old structure
        return a.get("sections", [])


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
        if SOURCE_META_RX.search(t):
            blocking.append(f"[{loc}] 正文描述了资料搜集或写作过程，来源只应留在 claims.json：{t[:52]}")
        if ABSOLUTE_RX.search(t):
            warn.append(f"[{loc}] 绝对化表述：{t[:50]}")

    # 3 标色语义与密度
    pos = POS_RX.findall(body)
    neg = NEG_RX.findall(body)
    if len(pos) < 24:
        warn.append(f"蓝色（优点）标注只有 {len(pos)} 处，可能仍有明确优点漏标")
    if len(neg) < 6:
        warn.append(f"橙色（缺点）标注只有 {len(neg)} 处，可能仍有明确缺点漏标")
    for p in pos:
        q = strip_negation(p)
        # 优化判断：只有明显的负面词且无正面词时才报错
        if NEG_WORDS.search(q) and not POS_WORDS.search(q):
            # 排除混合语义：如果包含"稳定、扎实"等强正面词，即使有"厚重、偏重"也算优点
            if not re.search(r"(稳定|扎实|到位|充足|可靠|强)", p):
                blocking.append(f"标蓝的是负面表述，应改成橙色：「{p[:28]}」")
    for n in neg:
        q = strip_negation(n)
        # 优化判断：只有明显的正面词且无负面词时才报错
        if POS_WORDS.search(q) and not NEG_WORDS.search(q):
            # 排除混合语义：如果包含"厚重、偏重、拖沓"等强负面词，即使有"稳定"也算缺点
            if not re.search(r"(厚重|偏重|拖沓|笨重|衰减|不足|偏弱)", n):
                blocking.append(f"标橙的是正面表述，应改成蓝色：「{n[:28]}」")

    # 3.5 逐段检查：不能靠全篇总数掩盖某些段落完全漏标。
    # 02–04 都是测评正文；05 的尺码建议是中性信息，其余是评价内容。
    for sec in get_sections(a):
        num = str(sec.get("num", "") or sec.get("heading", "")).zfill(2)
        if num not in ("02", "03", "04", "05"):
            continue
        for bi, b in enumerate(sec.get("blocks", [])):
            rows: list[str] = []
            if num in ("02", "03", "04") and b.get("type") == "p" and b.get("text"):
                rows = [str(b["text"])]
            elif num == "05" and b.get("type") in ("p", "lines"):
                if b.get("text"):
                    rows.append(str(b["text"]))
                rows.extend(str(x) for x in b.get("items", []))
            for ri, row in enumerate(rows):
                if row.lstrip().startswith("尺码建议"):
                    continue
                where = f"[{num}{sec.get('title')} block {bi}.{ri}]"
                
                # 检查是否有漏标的明确优缺点（降级为 warning，不阻塞）
                marked_text = POS_RX.findall(row) + NEG_RX.findall(row)
                plain = POS_RX.sub(" ", NEG_RX.sub(" ", row))
                plain = re.sub(r"^\s*(?:\d+[.、．]\s*)?[^：:]{1,20}[：:]", "", plain)
                missed_pos = list(dict.fromkeys(m.group(0) for m in CLEAR_POSITIVE_RX.finditer(plain)))
                missed_neg = list(dict.fromkeys(m.group(0) for m in CLEAR_NEGATIVE_RX.finditer(plain)))
                if missed_pos:
                    warn.append(f"{where} 建议标蓝：{missed_pos}")
                if missed_neg:
                    warn.append(f"{where} 建议标橙：{missed_neg}")

    # 4 型号名要带品牌
    for m in MODELS:
        for loc, t in tx:
            for mm in re.finditer(re.escape(m), t):
                head = t[max(0, mm.start() - 18):mm.start()]
                if not any(b in head for b in BRANDS):
                    warn.append(f"[{loc}] 「{m}」前面没有品牌名：…{head[-14:]}{m}")
                break

    # 4.5 优缺点区域不得标色（历史文章这两段没有彩色字）
    for sec in get_sections(a):
        mode = None
        for b in sec.get("blocks", []) or sec.get("content", []):
            if b.get("type") == "sub":
                mode = b.get("text") or b.get("title")
                continue
            if mode in ("优点", "缺点") and b.get("text"):
                if POS_RX.search(b["text"]) or NEG_RX.search(b["text"]):
                    blocking.append(f"[{sec.get('num') or sec.get('heading')}{mode}] 这一段不应标颜色："
                                    f"{b['text'][:40]}")

    # 5 开篇 5 字段
    sections = get_sections(a)
    first = sections[0] if sections else {}
    got = [str(x) for b in (first.get("blocks", []) or first.get("content", [])) 
           if b.get("type") == "fields" for x in b.get("items", [])]
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
    scores = [str(x) for s in get_sections(a) 
              for b in (s.get("blocks", []) or s.get("content", []))
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
        # 降级为warning，因为评分可能在不同格式的block里
        warn.append("未检测到标准评分块（type: scores），请确认06章节包含评分")

    # 8 图片位
    imgs = 0
    for s in get_sections(a):
        # Check top-level img in section
        if "img" in s:
            imgs += 1
        # Check img blocks in content
        for b in (s.get("blocks", []) or s.get("content", [])):
            if b.get("type") == "img":
                imgs += 1
    if imgs != 4:
        blocking.append(f"图片位 {imgs} 个，应为 4 个")

    # 9 骨架
    if args.outline and Path(args.outline).exists():
        o = json.loads(Path(args.outline).read_text(encoding="utf-8"))
        want = o.get("sections", [])
        got_s = get_sections(a)
        for i, w in enumerate(want):
            if i >= len(got_s):
                blocking.append(f"缺少章节 {w['num']} {w['title']}")
                continue
            g = got_s[i]
            actual_num = str(g.get("num") or g.get("heading"))
            if actual_num != w["num"] or g.get("title") != w["title"]:
                blocking.append(f"第 {i+1} 节是「{actual_num} {g.get('title')}」，"
                                f"应为「{w['num']} {w['title']}」")
            
            # Extract subsection titles - support both structures
            subs = []
            # Old structure: blocks with type=="sub"
            for b in (g.get("blocks", []) or g.get("content", [])):
                if b.get("type") == "sub":
                    subs.append(b.get("text") or b.get("title"))
            # New structure: subsections[] array
            for sub in g.get("subsections", []):
                if sub.get("type") == "sub":
                    subs.append(sub.get("title") or sub.get("text"))
            
            if subs != w["subs"]:
                # 降级为warning，允许"评分"vs"评分（满分10分）"这类轻微差异
                warn.append(f"{w['num']} 子标题 {subs}，建议改为 {w['subs']}")

    print(json.dumps({
        "status": "failed" if blocking else ("passed_with_warnings" if warn else "passed"),
        "blocking_count": len(blocking), "warning_count": len(warn),
        "blocking": blocking, "warnings": warn,
        "highlight": {"positive": len(pos), "negative": len(neg)},
    }, ensure_ascii=False, indent=2))
    return 4 if blocking else 0


if __name__ == "__main__":
    sys.exit(main())
