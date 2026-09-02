#!/usr/bin/env python3
"""内容准确性审核：把文章里的每个数字都钉到可核验的来源上。

设计目标是让"编不出来"——凡是正文出现带单位的数字，都必须在 claims.json 里登记，
且登记条目必须带原文引用，引用里必须真的出现这个数字。

用法:
  fact_check.py --article article.json --claims claims.json --report report.json
  fact_check.py --article a.json --claims c.json --report r.json --min-sources 2
退出码:
  0 通过（可能有 warning）  4 有 blocking 问题  2 输入错误
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

# 带单位的数字 —— 这类必须有来源
UNIT_RX = re.compile(
    r"(?P<num>\d+(?:\.\d+)?)\s*"
    r"(?P<unit>g|克|kg|mm|毫米|cm|厘米|码|%|％|元|块|人民币|美元|美金|\$|万|km|公里|分钟|秒|小时|双|天|年|个月|折)"
)
# 裸数字（含小数/千分位）
BARE_RX = re.compile(r"(?<![\w.])(\d{1,3}(?:,\d{3})+|\d+(?:\.\d+)?)(?![\w%])")

TEXT_BLOCKS = {"p", "quote", "h2", "h3"}

# 日期不是需要来源的数值，先屏蔽掉
DATE_RX = re.compile(
    r"(\d{4}\s*[-/年]\s*\d{1,2}\s*[-/月]\s*\d{1,2}\s*日?|\d{4}\s*[-/年]\s*\d{1,2}\s*月?|\d{1,2}\s*月\s*\d{1,2}\s*日)"
)
# 评分 8/10、8.2/10 是主观打分，同样不需要来源
SCORE_RX = re.compile(r"\d+(?:\.\d+)?\s*(?:/\s*10\b|分(?!钟))")
# 鞋码（男款 44.5 码 / US 9）属产品属性，随重量口径一起登记即可
SIZE_RX = re.compile(r"(?:US|us)\s*\d+(?:\.\d+)?|\d+(?:\.\d+)?\s*码")

# 跑鞋常见指标的合理区间，超出即 blocking（防止把 mm 和 cm 写错这类硬错）
RANGES: dict[str, tuple[float, float, str]] = {
    "重量": (120, 400, "g"),
    "单只重量": (120, 400, "g"),
    "前掌堆高": (10, 45, "mm"),
    "后跟堆高": (15, 55, "mm"),
    "堆高": (10, 55, "mm"),
    "落差": (0, 14, "mm"),
    "跟差": (0, 14, "mm"),
    "官方定价": (200, 3000, "元"),
    "发售价": (200, 3000, "元"),
    "二级市场价": (100, 5000, "元"),
    "得物价": (100, 5000, "元"),
}

SECONDARY_MARKET_HOSTS = ("dewu.com", "poizon.com", "du.hupu.com")


def norm_num(s: str) -> str:
    s = s.replace(",", "")
    try:
        f = float(s)
    except ValueError:
        return s
    return str(int(f)) if f.is_integer() else str(f)


# 前置货币符号：¥999 / ￥899 / $120 —— 与「999元」等价对待
CUR_PREFIX_RX = re.compile(r"[¥￥$]\s*(\d+(?:\.\d+)?)")


def numbers_in(text: str) -> tuple[set[str], set[tuple[str, str]]]:
    """返回 (裸数字集合, (数字, 单位) 集合)。日期、评分、鞋码先屏蔽。"""
    text = DATE_RX.sub(" ", text)
    text = SCORE_RX.sub(" ", text)
    text = SIZE_RX.sub(" ", text)
    united = {(norm_num(m.group("num")), m.group("unit")) for m in UNIT_RX.finditer(text)}
    united |= {(norm_num(m.group(1)), "元") for m in CUR_PREFIX_RX.finditer(text)}
    bare = {norm_num(m.group(1)) for m in BARE_RX.finditer(text)}
    return bare, united


def host(url: str) -> str:
    try:
        h = urlparse(url).netloc.lower()
    except Exception:  # noqa: BLE001
        return ""
    return h[4:] if h.startswith("www.") else h


def registered_domain(h: str) -> str:
    parts = h.split(".")
    if len(parts) <= 2:
        return h
    # 处理 com.cn / co.uk 这类
    if parts[-2] in ("com", "co", "net", "org", "gov", "edu") and len(parts[-1]) == 2:
        return ".".join(parts[-3:])
    return ".".join(parts[-2:])


class Issue(dict):
    def __init__(self, severity: str, code: str, message: str, **extra):
        super().__init__(severity=severity, code=code, message=message, **extra)


def collect_article_text(article: dict) -> list[tuple[str, str]]:
    out: list[tuple[str, str]] = []

    def walk(blocks: list, prefix: str) -> None:
        for i, b in enumerate(blocks):
            t = b.get("type")
            loc = f"{prefix}[{i}].{t}"
            if t in TEXT_BLOCKS or t == "sub":
                if b.get("text"):
                    out.append((loc, b["text"]))
            elif t in ("list", "olist", "fields", "scores", "lines"):
                for j, it in enumerate(b.get("items", [])):
                    out.append((f"{loc}[{j}]", str(it)))
            elif t == "table":
                for j, row in enumerate(b.get("rows", [])):
                    out.append((f"{loc}.row[{j}]", " | ".join(str(c) for c in row)))
                if b.get("caption"):
                    out.append((f"{loc}.caption", b["caption"]))
            elif t == "img" and b.get("caption"):
                out.append((f"{loc}.caption", b["caption"]))

    # 通用模式
    walk(article.get("blocks", []), "block")
    # 模板模式：sections[].blocks[]
    for si, s in enumerate(article.get("sections", [])):
        tag = f"{s.get('num', si)}{s.get('title', '')}"
        walk(s.get("blocks", []), f"[{tag}]block")
    if article.get("title"):
        out.append(("title", article["title"]))
    if article.get("digest"):
        out.append(("digest", article["digest"]))
    return out


def validate_claims(claims: list[dict], min_sources: int) -> tuple[list[Issue], dict[str, set[str]]]:
    issues: list[Issue] = []
    # (subject, metric) -> 值集合，用于冲突检测
    by_key: dict[tuple[str, str], set[str]] = defaultdict(set)
    covered: dict[str, set[str]] = {"numbers": set(), "units": set()}

    seen_ids: set[str] = set()
    for idx, c in enumerate(claims):
        cid = c.get("id") or f"#{idx}"
        if cid in seen_ids:
            issues.append(Issue("blocking", "duplicate_id", f"claim id 重复: {cid}", claim=cid))
        seen_ids.add(cid)

        value = str(c.get("value", "")).strip()
        if not value:
            issues.append(Issue("blocking", "empty_value", f"{cid} 缺少 value", claim=cid))
            continue
        subject = str(c.get("subject", "")).strip()
        metric = str(c.get("metric", "")).strip()
        if not subject or not metric:
            issues.append(
                Issue("warning", "missing_subject_metric", f"{cid} 缺少 subject/metric", claim=cid)
            )

        bare, united = numbers_in(value)
        is_numeric = bool(bare or united)
        covered["numbers"] |= bare
        covered["units"] |= {f"{n}{u}" for n, u in united}

        sources = c.get("sources") or []
        if not sources:
            issues.append(Issue("blocking", "no_source", f"{cid} 没有任何来源", claim=cid))
        domains = {registered_domain(host(s.get("url", ""))) for s in sources if s.get("url")}
        domains.discard("")
        hosts = {host(s.get("url", "")) for s in sources if s.get("url")}
        is_secondary = bool(metric) and ("二级" in metric or "得物" in metric)
        dewu_sourced = any(any(h.endswith(sm) for sm in SECONDARY_MARKET_HOSTS) for h in hosts)
        sole_ok = bool(c.get("sole_source_ok"))
        sole_reason = str(c.get("sole_source_reason", "")).strip()
        if is_secondary and dewu_sourced:
            need = 1  # 得物是唯一口径，不要求第二来源，但 date 必填
        elif sole_ok:
            need = 1  # 显式声明的单一权威来源（如全球唯一实验室），必须写明理由
            if not sole_reason:
                issues.append(
                    Issue("blocking", "sole_source_no_reason",
                          f"{cid} 声明了 sole_source_ok 但没写 sole_source_reason", claim=cid)
                )
            else:
                issues.append(
                    Issue("warning", "sole_source_used",
                          f"{cid} 单一来源，理由：{sole_reason}", claim=cid)
                )
        else:
            need = min_sources if is_numeric else 1
        if sources and len(domains) < need:
            sev = "blocking" if is_numeric else "warning"
            issues.append(
                Issue(
                    sev,
                    "insufficient_sources",
                    f"{cid} 数值类结论只有 {len(domains)} 个独立来源域名，要求 {need} 个",
                    claim=cid,
                    domains=sorted(domains),
                )
            )

        # 引用必须真的包含这个数字
        for s in sources:
            url = s.get("url", "")
            if not url:
                issues.append(Issue("blocking", "source_no_url", f"{cid} 有来源但缺 url", claim=cid))
                continue
            quote = str(s.get("quote", ""))
            if not quote:
                issues.append(
                    Issue("blocking", "source_no_quote", f"{cid} 来源 {url} 缺少 quote 原文引用",
                          claim=cid, url=url)
                )
                continue
            if is_numeric:
                qbare, qunited = numbers_in(quote)
                qnums = qbare | {n for n, _ in qunited}
                anums = bare | {n for n, _ in united}
                if not (anums & qnums):
                    issues.append(
                        Issue(
                            "blocking",
                            "quote_mismatch",
                            f"{cid} 的值 {value} 在来源引文中找不到对应数字",
                            claim=cid,
                            url=url,
                            quote=quote[:160],
                        )
                    )
            if not s.get("date") and not s.get("accessed"):
                issues.append(
                    Issue("warning", "source_no_date", f"{cid} 来源 {url} 缺少日期", claim=cid, url=url)
                )

        # 二级市场价必须来自得物系
        if is_secondary and not dewu_sourced:
            issues.append(
                Issue(
                    "warning",
                    "price_source_not_dewu",
                    f"{cid} 是二级市场价但来源不是得物: {sorted(hosts)}",
                    claim=cid,
                )
            )
        # 价格是浮动的，缺采集日期直接拦
        if is_secondary and not any(s.get("date") or s.get("accessed") for s in sources):
            issues.append(
                Issue("blocking", "price_no_date", f"{cid} 是价格类结论但没有任何采集日期", claim=cid)
            )

        # 区间合理性
        for key, (lo, hi, unit) in RANGES.items():
            if metric and key in metric:
                nums = [float(n) for n in (bare | {n for n, _ in united})]
                bad = [n for n in nums if not lo <= n <= hi]
                if bad and nums:
                    issues.append(
                        Issue(
                            "blocking",
                            "out_of_range",
                            f"{cid} {metric}={value} 超出合理区间 {lo}–{hi}{unit}",
                            claim=cid,
                        )
                    )
                break

        if subject and metric:
            by_key[(subject, metric)].add(value)

    for (subject, metric), vals in by_key.items():
        if len(vals) > 1:
            issues.append(
                Issue(
                    "blocking",
                    "conflict",
                    f"同一指标存在冲突值：{subject} / {metric} = {sorted(vals)}",
                    subject=subject,
                    metric=metric,
                )
            )
    return issues, covered


def check_coverage(article: dict, covered: dict[str, set[str]], allow: set[str]) -> list[Issue]:
    issues: list[Issue] = []
    for loc, text in collect_article_text(article):
        bare, united = numbers_in(text)
        for n, u in sorted(united):
            token = f"{n}{u}"
            if token in covered["units"] or n in covered["numbers"] or token in allow or n in allow:
                continue
            issues.append(
                Issue(
                    "blocking",
                    "unsourced_number",
                    f"{loc} 出现未登记的带单位数字 {token}",
                    location=loc,
                    value=token,
                    snippet=text[:120],
                )
            )
        united_nums = {n for n, _ in united}
        for n in sorted(bare - united_nums):
            if n in covered["numbers"] or n in allow:
                continue
            if len(n) <= 2 and float(n) <= 12:
                continue  # 序号类小数字放过
            issues.append(
                Issue(
                    "warning",
                    "unsourced_bare_number",
                    f"{loc} 出现未登记的数字 {n}",
                    location=loc,
                    value=n,
                    snippet=text[:120],
                )
            )
    return issues


def check_hedging(article: dict) -> list[Issue]:
    """绝对化表述提示。"""
    issues: list[Issue] = []
    rx = re.compile(r"(最强|第一|唯一|绝对|必买|稳赚|无脑买|肯定|100%|完胜|吊打)")
    for loc, text in collect_article_text(article):
        for m in rx.finditer(text):
            issues.append(
                Issue("warning", "absolute_claim", f"{loc} 出现绝对化表述「{m.group(1)}」",
                      location=loc, snippet=text[:120])
            )
    return issues


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="文章事实核查")
    ap.add_argument("--article", required=True)
    ap.add_argument("--claims", required=True)
    ap.add_argument("--report", required=True)
    ap.add_argument("--min-sources", type=int, default=2, help="数值类结论要求的独立来源域名数")
    ap.add_argument("--allow-unsourced", default="", help="逗号分隔的白名单数字，如 2025,2026")
    args = ap.parse_args(argv)

    try:
        article = json.loads(Path(args.article).expanduser().read_text(encoding="utf-8"))
        raw = json.loads(Path(args.claims).expanduser().read_text(encoding="utf-8"))
    except Exception as exc:  # noqa: BLE001
        print(json.dumps({"status": "input_error", "error": str(exc)}, ensure_ascii=False))
        return 2

    claims = raw.get("claims", raw) if isinstance(raw, dict) else raw
    if not isinstance(claims, list):
        print(json.dumps({"status": "input_error", "error": "claims 必须是数组"}, ensure_ascii=False))
        return 2

    allow = {norm_num(x.strip()) for x in args.allow_unsourced.split(",") if x.strip()}
    allow |= {norm_num(str(x)) for x in article.get("unsourced_ok", [])}

    issues, covered = validate_claims(claims, args.min_sources)
    issues += check_coverage(article, covered, allow)
    issues += check_hedging(article)

    blocking = [i for i in issues if i["severity"] == "blocking"]
    warnings = [i for i in issues if i["severity"] == "warning"]
    report = {
        "status": "failed" if blocking else ("passed_with_warnings" if warnings else "passed"),
        "claims": len(claims),
        "blocking_count": len(blocking),
        "warning_count": len(warnings),
        "blocking": blocking,
        "warnings": warnings,
    }
    out = Path(args.report).expanduser()
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({k: report[k] for k in ("status", "claims", "blocking_count", "warning_count")},
                     ensure_ascii=False, indent=2))
    for i in blocking[:20]:
        print(f"  [BLOCK] {i['code']}: {i['message']}", file=sys.stderr)
    for i in warnings[:20]:
        print(f"  [warn ] {i['code']}: {i['message']}", file=sys.stderr)
    return 4 if blocking else 0


if __name__ == "__main__":
    sys.exit(main())
