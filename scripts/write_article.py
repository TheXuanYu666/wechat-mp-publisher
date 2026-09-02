#!/usr/bin/env python3
"""让 App 自己写稿：调用本机 kiro-cli（复用你已有订阅，不需要额外 API key）。

做的事：给 kiro-cli 一条带完整约束的指令，让它按 wechat-mp-publisher 的规则
搜数据、写 claims.json 与 article.json，然后本脚本校验产物是否齐全。

进度按行输出 `PROGRESS <pct> <说明>`。

用法:
  write_article.py --shoe "Nike Vomero Plus" --column 跑鞋篇 [--effort high]
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

SKILL = Path(__file__).resolve().parent.parent
import sys as _s; _s.path.insert(0, str(Path(__file__).resolve().parent.parent))
from config import assets_root as _ar  # noqa: E402

ROOT = _ar()


def find_kiro() -> str | None:
    """GUI 启动的 App 继承不到用户 shell 的 PATH，必须按绝对路径找。"""
    import shutil

    cands = [
        Path.home() / ".local/bin/kiro-cli",
        Path("/Applications/Kiro CLI.app/Contents/MacOS/kiro-cli"),
        Path("/usr/local/bin/kiro-cli"),
        Path("/opt/homebrew/bin/kiro-cli"),
    ]
    for c in cands:
        if c.exists():
            return str(c)
    w = shutil.which("kiro-cli")
    return w


def progress(pct: int, msg: str) -> None:
    print(f"PROGRESS {pct} {msg}", flush=True)


PROMPT = """请为公众号「RDFZ 步界社」写一篇 {column} 测评，鞋款：{shoe}。

严格遵守 skill `wechat-mp-publisher` 的全部规则，重点：

1. 骨架照 {skill}/references/outline-shoe-review.md 的 {column}，章节号、章节名、子标题、
   开篇 5 字段一字不差。跑鞋与篮球鞋的 02/03/04 子标题不同，不要混用。
2. 先搜数据：国内用 istarshine 全网搜，海外优先 RunRepeat（实验室实测）、品牌官网规格页。
   每个数值都要落进 claims.json，字段为 subject/metric/value/sources[{{url,title,quote,date}}]，
   quote 必须是含该数字的原文。单位换算成公制后写 value，quote 保留原文。
   全球只有一家实验室的数据，用 sole_source_ok=true 并写明 sole_source_reason。
3. 正文里**绝对不要提任何外部网站、媒体、实验室、评测机构的名字**，也不要写「据某某测试」
   「官方数据显示」这类话。来源只登记在 claims.json 里做内部核查，正文直接给结论。
4. 用第一体验视角写，但不得虚构没发生过的经历。照这个标准把握：

   可以写（把数据翻译成上脚感受）：
     · 上脚偏软，落地几乎感觉不到路面的硬
     · 跑起来后跟会自然往前滚，蹬起来省劲
     · 鞋头空间偏窄，脚趾展不开
     · 前掌垫得薄，路感清楚但保护有限
   不能写（只有真穿过才知道的具体数字与时间）：
     · 我跑了 30 公里后感觉缓震开始衰减
     · 配速 5 分以内推进力才明显
     · 穿了两周之后鞋面开始起毛
     · 全马 3 小时 30 分水平可驾驭

   也就是说：**感受可以描述，经历不能编**。每个带单位的数字仍须在 claims.json 有据。

4c. 正文里不要用「」这种引号，要强调就用蓝色/橙色标记，不要靠引号。

4b. **不做横向比较，只说这双鞋本身的事实。** 不要写「同价位里算好的」「比同类均值高」
   「在这个价位不常见」「比大多数竞品」这类话。透气差就直接写透气差，哪怕它在同价位里
   不算差；耐磨好就直接写耐磨好。与上一代的纵向对比可以写（例如「比上一代提升将近一倍」）。
5. 写作口吻按社团定位：大白话，不要出现 SA / BR / AC / Nm 这类实验室缩写，
   也不要写 v41 这种写法（用「上一代」）。提到其他鞋款要带品牌名。
   不写产品改进建议、不引导读者去买别的鞋，只讲客观体验和优缺点。
4. 行内强调只有两种：**优点短句** 出蓝色，~~缺点短句~~ 出橙色。一段标 2–4 处，
   全篇蓝色 30 处左右、橙色 10 处左右。
5. 优缺点条数不限，但正文里提到的优点和缺点都必须进列表；**优点与缺点这两段的条目一律不标颜色**
   （历史文章里这两段没有任何彩色字）；缺点只写鞋本身性能问题，
   不写性价比。评分：跑鞋 5 项写 X/10，篮球鞋 7 项写 X 分。
6. 结论句式：定位句 → 凭借哪些优势成为哪类人的选择 → 次要优点提升什么场景 →
   但哪些短板限制了适用场景 → 建议作为什么鞋使用、主要用于什么、避免什么。
7. 文末 footer 只要 tester/editor（都写{测评人}）和 date，不要 reviewers。
8. 开篇字段里**只有「二级平台价格」允许写「待补」**（由 App 里的操作者填）。
   「官方发售价」必须去查到具体数字，优先查品牌中国官网的国行价（写成 ¥XXX），
   查不到国行价再用官方美价并注明币种。**不许写「待补」或留空**。
   「产品定位」「实测重量」同样必须有具体内容。
9. 四张图片位：01/02/03/04 各一个 img 块，url 先写 "TODO_上传素材库后回填"，
   由 App 负责上传与回填。不要自己找图。

产物写到这两个文件（目录不存在就创建）：
  {workdir}/claims.json
  {workdir}/article.json

写完后跑一次核查确认 blocking 为 0：
  {py} {skill}/scripts/fact_check.py --article {workdir}/article.json \\
    --claims {workdir}/claims.json --report {workdir}/tmp/factcheck.json --min-sources 2

全部完成后只回复一行：DONE
"""


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="调 kiro-cli 写稿")
    ap.add_argument("--shoe", required=True)
    ap.add_argument("--column", required=True)
    ap.add_argument("--effort", default="high")
    ap.add_argument("--timeout", type=int, default=2400)
    args = ap.parse_args(argv)

    if not ROOT.exists():
        print(json.dumps({"status": "no_volume", "error": f"素材盘未挂载：{ROOT}"},
                         ensure_ascii=False))
        return 7

    wd = ROOT / args.shoe
    wd.mkdir(parents=True, exist_ok=True)
    (wd / "tmp").mkdir(exist_ok=True)
    py = SKILL / ".venv" / "bin" / "python"

    prompt = PROMPT.format(shoe=args.shoe, column=args.column, skill=SKILL,
                           workdir=wd, py=py)

    progress(5, f"交给 kiro-cli 写《{args.column}——{args.shoe}》")
    kiro = find_kiro()
    if not kiro:
        print(json.dumps({"status": "no_kiro",
                          "error": "找不到 kiro-cli，装在别处的话告诉我路径"},
                         ensure_ascii=False))
        return 6
    cmd = [kiro, "chat", "--no-interactive", "--agent", "wechat-mp",
           "--effort", args.effort, "--trust-all-tools", prompt]

    progress(12, "搜集数据与撰写中，这一步比较久，请耐心等")
    try:
        p = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                             text=True, bufsize=1, errors="replace", cwd=str(SKILL))
    except FileNotFoundError:
        print(json.dumps({"status": "no_kiro", "error": f"无法执行 {kiro}"},
                         ensure_ascii=False))
        return 6

    pct, tail = 12, []
    for line in p.stdout or []:
        tail.append(line.rstrip()[:200])
        if len(tail) > 40:
            tail.pop(0)
        if pct < 88:
            pct += 1
            progress(pct, "撰写中…")
    try:
        p.wait(timeout=args.timeout)
    except subprocess.TimeoutExpired:
        p.kill()
        print(json.dumps({"status": "timeout", "tail": tail[-8:]}, ensure_ascii=False))
        return 8

    progress(92, "校验产物")
    art, cl = wd / "article.json", wd / "claims.json"
    problems = []
    if not art.exists():
        problems.append("没有生成 article.json")
    if not cl.exists():
        problems.append("没有生成 claims.json")
    if art.exists():
        try:
            a = json.loads(art.read_text(encoding="utf-8"))
            if len(a.get("sections", [])) != 6:
                problems.append(f"章节数 {len(a.get('sections', []))}，应为 6")
            imgs = sum(1 for s in a.get("sections", []) for b in s.get("blocks", [])
                       if b.get("type") == "img")
            if imgs != 4:
                problems.append(f"图片位 {imgs} 个，应为 4")
        except Exception as exc:  # noqa: BLE001
            problems.append(f"article.json 解析失败：{exc}")

    fc = wd / "tmp" / "factcheck.json"
    blocking = None
    if fc.exists():
        try:
            blocking = json.loads(fc.read_text(encoding="utf-8")).get("blocking_count")
        except Exception:  # noqa: BLE001
            pass

    progress(100, "完成" if not problems else "产物不完整")
    print(json.dumps({
        "status": "ok" if not problems else "incomplete",
        "workdir": str(wd), "problems": problems,
        "fact_check_blocking": blocking, "tail": tail[-6:],
    }, ensure_ascii=False))
    return 0 if not problems else 9


if __name__ == "__main__":
    sys.exit(main())
