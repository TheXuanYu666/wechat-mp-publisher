#!/usr/bin/env python3
"""步界社公众号生成器 · 本地 App 后端（Python 标准库，无额外依赖）。

三步流程：
  1. 填二级市场价格区间
  2. 拖入 4 张图片
  3. 生成（事实核查 → 组件模板渲染）→ 预览 → 可选：发布到公众号草稿

启动：
  ~/.kiro/skills/wechat-mp-publisher/.venv/bin/python app/server.py
  然后浏览器打开 http://127.0.0.1:8765

安全边界：只监听 127.0.0.1，不对外网开放；不做鉴权是因为仅本机可访问。
发布只写草稿，永不点发表/群发。
"""
from __future__ import annotations

import base64
import datetime
import json
import os
import re
import subprocess
import sys
import threading
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

SKILL = Path(__file__).resolve().parent.parent
SCRIPTS = SKILL / "scripts"
PY = SKILL / ".venv" / "bin" / "python"
TEMPLATE = SKILL / "references" / "template_rdfz.json"
OUTLINE = SKILL / "references" / "outline_running.json"
OUTLINE_BB = SKILL / "references" / "outline_basketball.json"


def outline_for(column: str) -> Path:
    """跑鞋和篮球鞋骨架不同，校验和渲染都要用对应那份。"""
    if ("篮球" in (column or "") or "球鞋" in (column or "")) and OUTLINE_BB.exists():
        return OUTLINE_BB
    return OUTLINE
CANDS = SKILL / "references" / "candidates.json"
sys.path.insert(0, str(SKILL))
from config import CFG, assets_root  # noqa: E402

ROOT_ASSETS = assets_root()
WORKDIR = ROOT_ASSETS / "Nike Pegasus 42"
LOGO = Path(CFG.get("cover", {}).get("logo", ""))
HOST, PORT = "127.0.0.1", 8765

IMG_SLOTS = [
    ("01", "第一个图片", "开篇简介"),
    ("02", "第二个图片", "外观设计与做工"),
    ("03", "第三个图片", "中底性能"),
    ("04", "第四个图片", "外底与耐久性"),
]


# GUI 启动时 PATH 是系统默认的，缺少用户目录，子进程会找不到 kiro-cli / node
ENV = {
    **os.environ,
    "PATH": ":".join([
        str(Path.home() / ".local/bin"), "/usr/local/bin", "/opt/homebrew/bin",
        os.environ.get("PATH", "/usr/bin:/bin:/usr/sbin:/sbin"),
    ]),
}


def run(cmd: list[str], timeout: int = 900) -> tuple[int, str, str]:
    p = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout,
                       errors="replace", env=ENV)
    return p.returncode, p.stdout, p.stderr


def tail_json(text: str) -> dict[str, Any]:
    """脚本输出末尾是 JSON，取出来。"""
    t = text.strip()
    start = t.rfind("{")
    while start != -1:
        try:
            return json.loads(t[start:])
        except Exception:  # noqa: BLE001
            start = t.rfind("{", 0, start)
    return {}


class Pipeline:
    """把价格与图片写进 article.json，再跑核查与渲染。"""

    def __init__(self, workdir: Path, column: str = ""):
        self.d = workdir
        self.column = column
        self.article = workdir / "article.json"
        self.claims = workdir / "claims.json"
        self.html = workdir / "article.html"
        self.tmp = workdir / "tmp"
        self.imgs = workdir / "app_imgs"

    def check_env(self) -> list[str]:
        bad = []
        if not self.d.exists():
            bad.append(f"工作目录不存在（素材盘没挂载？）：{self.d}")
        if not self.article.exists():
            bad.append(f"缺少 article.json：{self.article}")
        if not TEMPLATE.exists():
            bad.append("缺少排版组件模板 template_rdfz.json")
        return bad

    def save_images(self, items: list[dict[str, str]]) -> list[Path]:
        self.imgs.mkdir(parents=True, exist_ok=True)
        out = []
        for it in items:
            raw = it.get("data", "")
            if "," in raw:
                raw = raw.split(",", 1)[1]
            name = re.sub(r"[^\w.\-]", "_", it.get("name", "img"))[-50:]
            ext = Path(name).suffix.lower() or ".png"
            if ext not in (".png", ".jpg", ".jpeg"):
                ext = ".png"
            p = self.imgs / f"{it['slot']}{ext}"
            p.write_bytes(base64.b64decode(raw))
            out.append(p)
        return out

    def set_publish_date(self, iso: str) -> str:
        """写文末发布日期。存的是本号历史格式：YYYY年M月D日（月日不补零）。"""
        a = json.loads(self.article.read_text(encoding="utf-8"))
        if iso:
            y, m, d = iso.split("-")
            txt = f"{int(y)}年{int(m)}月{int(d)}日"
        else:
            t = datetime.date.today()
            txt = f"{t.year}年{t.month}月{t.day}日"
        a.setdefault("footer", {})["date"] = txt
        self.article.write_text(json.dumps(a, ensure_ascii=False, indent=2), encoding="utf-8")
        return txt

    MISSING_RX = re.compile(r"(待补|待定|待填|TODO)")

    @staticmethod
    def normalize_fill_value(label: str, value: str) -> tuple[str, str]:
        """规范化 App 手填值；返回 (规范值, 错误)。"""
        value = str(value or "").strip()
        if not value:
            return "", f"{label}不能为空"
        if label != "官方发售价":
            return value, ""

        if re.search(r"(?:US\s*\$|USD|美元|美金|\$)", value, re.I):
            return "", "官方发售价必须是中国大陆人民币价格；只写数字即可，例如 1490"
        compact = re.sub(r"[\s,，]", "", value)
        m = re.fullmatch(r"(?:人民币)?[¥￥]?(\d{2,5})(?:元)?", compact)
        if not m:
            return "", "官方发售价格式不对；只写数字即可，例如 1490（会自动变成 ¥1490）"
        amount = int(m.group(1))
        if not 200 <= amount <= 3000:
            return "", "官方发售价应为 200～3000 元；请确认后重新输入"
        return f"¥{amount}", ""

    def _sync_existing_manual_claim(self, label: str, value: str) -> None:
        """正文里的旧手填值被规范化时，同步修正对应 manual claim。"""
        if not self.claims.exists():
            return
        c = json.loads(self.claims.read_text(encoding="utf-8"))
        rows = c.get("claims", []) if isinstance(c, dict) else []
        cid = "manual_" + re.sub(r"\W+", "_", label)
        changed = False
        for row in rows:
            if row.get("id") != cid:
                continue
            row["value"] = value
            for src in row.get("sources") or []:
                src["quote"] = f"{label}：{value}"
            changed = True
        if changed:
            self.claims.write_text(json.dumps(c, ensure_ascii=False, indent=2), encoding="utf-8")

    def missing_fields(self) -> list[dict[str, str]]:
        """找出待补或格式非法的开篇字段；合法裸数字发售价会自动规范化。"""
        a = json.loads(self.article.read_text(encoding="utf-8"))
        out: list[dict[str, str]] = []
        normalized: list[tuple[str, str]] = []
        changed = False
        for s in a.get("sections", []):
            for b in s.get("blocks", []):
                if b.get("type") != "fields":
                    continue
                new = []
                for item in b.get("items", []):
                    x = str(item)
                    label, _, raw = x.partition("：")
                    if label == "二级平台价格":
                        new.append(x)
                        continue
                    if self.MISSING_RX.search(x):
                        out.append({"label": label, "current": x})
                    elif label == "官方发售价":
                        value, error = self.normalize_fill_value(label, raw)
                        if error:
                            out.append({"label": label, "current": x, "error": error})
                        elif value != raw.strip():
                            x = f"{label}：{value}"
                            normalized.append((label, value))
                            changed = True
                    new.append(x)
                b["items"] = new
        if changed:
            self.article.write_text(json.dumps(a, ensure_ascii=False, indent=2), encoding="utf-8")
            for label, value in normalized:
                self._sync_existing_manual_claim(label, value)
        return out

    def register_manual_claim(self, label: str, value: str) -> None:
        """手填的数字也要登记成可核查数据，否则事实核查会拦下来。
        来源标注为用户提供，并声明单一来源理由。
        """
        if not re.search(r"\d", value):
            return
        c = json.loads(self.claims.read_text(encoding="utf-8"))
        a = json.loads(self.article.read_text(encoding="utf-8"))
        cid = "manual_" + re.sub(r"\W+", "_", label)
        entry = {
            "id": cid,
            "subject": a.get("shoe", self.d.name),
            "metric": label,
            "value": value,
            "sole_source_ok": True,
            "sole_source_reason": "由运营者在 App 里手工补填（网上未检索到，属官方口径）",
            "sources": [{
                "title": f"运营者提供的{label}",
                "url": "https://mp.weixin.qq.com/",
                "quote": f"{label}：{value}",
                "date": datetime.date.today().isoformat(),
            }],
        }
        c["claims"] = [x for x in c["claims"] if x.get("id") != cid] + [entry]
        self.claims.write_text(json.dumps(c, ensure_ascii=False, indent=2), encoding="utf-8")

    def fill_fields(self, values: dict[str, str]) -> dict[str, Any]:
        """校验并写回补填内容；非法值不落盘，直接返回给前端重新输入。"""
        prepared: dict[str, str] = {}
        errors: list[dict[str, str]] = []
        for label, raw in values.items():
            value, error = self.normalize_fill_value(str(label), str(raw))
            if error:
                errors.append({"label": str(label), "current": str(raw), "error": error})
            else:
                prepared[str(label)] = value
        if errors:
            return {"done": [], "errors": errors}

        a = json.loads(self.article.read_text(encoding="utf-8"))
        done: list[str] = []
        registered: list[tuple[str, str]] = []
        for s in a.get("sections", []):
            for b in s.get("blocks", []):
                if b.get("type") != "fields":
                    continue
                new = []
                for item in b.get("items", []):
                    x = str(item)
                    label = x.split("：")[0]
                    value = prepared.get(label, "")
                    replaceable = self.MISSING_RX.search(x) or label == "官方发售价"
                    if value and replaceable:
                        x = f"{label}：{value}"
                        done.append(label)
                        registered.append((label, value))
                    new.append(x)
                b["items"] = new
        self.article.write_text(json.dumps(a, ensure_ascii=False, indent=2), encoding="utf-8")
        for label, value in registered:
            self.register_manual_claim(label, value)
        return {"done": done, "errors": []}

    def set_price(self, low: str, high: str) -> str:
        a = json.loads(self.article.read_text(encoding="utf-8"))
        val = f"二级平台价格：¥{low}～¥{high}"
        for s in a.get("sections", []):
            for b in s.get("blocks", []):
                if b.get("type") == "fields":
                    b["items"] = [
                        val if str(x).startswith("二级平台价格") else x for x in b["items"]
                    ]
        self.article.write_text(json.dumps(a, ensure_ascii=False, indent=2), encoding="utf-8")
        return val

    def register_price_claim(self, low: str, high: str, date: str = "") -> None:
        date = date or datetime.date.today().isoformat()
        c = json.loads(self.claims.read_text(encoding="utf-8"))
        cid = "price_dewu_range"
        entry = {
            "id": cid,
            "subject": json.loads(self.article.read_text(encoding="utf-8")).get("shoe", ""),
            "metric": "得物二级市场价（主流配色区间）",
            "value": f"{low}–{high}元",
            "sources": [
                {
                    "title": "得物 App 页面显示价（用户提供）",
                    "url": "https://www.dewu.com/",
                    "quote": f"主流配色 {low} 元起，最高 {high} 元",
                    "date": date,
                }
            ],
        }
        c["claims"] = [x for x in c["claims"] if x.get("id") != cid] + [entry]
        self.claims.write_text(json.dumps(c, ensure_ascii=False, indent=2), encoding="utf-8")

    def next_index(self) -> int:
        """新一篇的序号 = 已发文章数 + 1，用作素材库分组名。"""
        led = SKILL / "references" / "published.json"
        n = 0
        if led.exists():
            try:
                n = len(json.loads(led.read_text(encoding="utf-8")).get("written", []))
            except Exception:  # noqa: BLE001
                n = 0
        return n + 1

    def upload(self, paths: list[Path]) -> dict[str, Any]:
        cmd = [str(PY), str(SCRIPTS / "mp_draft.py"), "--timeout", "300", "upload",
               "--headless", "--group", str(self.next_index())]
        for p in paths:
            cmd += ["--image", str(p)]
        cmd += ["--out", str(self.tmp / "uploaded.json")]
        rc, so, se = run(cmd)
        return {"rc": rc, "result": tail_json(so), "stderr": se[-400:]}

    def set_image_urls(self, mapping: dict[str, str]) -> int:
        a = json.loads(self.article.read_text(encoding="utf-8"))
        n = 0
        for s in a.get("sections", []):
            num = s.get("num")
            if num in mapping:
                for b in s.get("blocks", []):
                    if b.get("type") == "img":
                        b["url"] = mapping[num]
                        n += 1
                        break
        self.article.write_text(json.dumps(a, ensure_ascii=False, indent=2), encoding="utf-8")
        return n

    def cleanup(self) -> list[str]:
        """删掉本次生成的临时图片，只保留封面与最终产物，避免占磁盘。"""
        removed = []
        if self.imgs.exists():
            for f in self.imgs.iterdir():
                try:
                    f.unlink()
                    removed.append(f.name)
                except Exception:  # noqa: BLE001
                    pass
            try:
                self.imgs.rmdir()
            except Exception:  # noqa: BLE001
                pass
        return removed

    def make_cover(self, side_view: Path, shoe: str = "") -> dict[str, Any]:
        out = self.d / "封面.png"
        if not shoe and self.article.exists():
            try:
                shoe = json.loads(self.article.read_text(encoding="utf-8")).get("shoe", "")
            except Exception:  # noqa: BLE001
                shoe = ""
        rc, so, se = run([
            str(PY), str(SCRIPTS / "make_cover.py"),
            "--shoe", shoe or self.d.name,
            "--side-view", str(side_view), "--out", str(out),
        ])
        r = tail_json(so)
        r["rc"] = rc
        if se:
            r["stderr"] = se[-200:]
        return r

    def fact_check(self) -> dict[str, Any]:
        self.tmp.mkdir(parents=True, exist_ok=True)
        rc, so, se = run([
            str(PY), str(SCRIPTS / "fact_check.py"),
            "--article", str(self.article), "--claims", str(self.claims),
            "--report", str(self.tmp / "factcheck.json"), "--min-sources", "2",
        ])
        rep = {}
        f = self.tmp / "factcheck.json"
        if f.exists():
            rep = json.loads(f.read_text(encoding="utf-8"))
        blocking = rep.get("blocking", [])
        return {
            "rc": rc,
            "status": rep.get("status"),
            "blocking_count": len(blocking),
            "blocking": [{"code": i["code"], "message": i["message"]} for i in blocking[:12]],
            "warning_count": rep.get("warning_count", 0),
        }

    def outline_path(self) -> Path:
        col = self.column
        if not col and self.article.exists():
            try:
                col = json.loads(self.article.read_text(encoding="utf-8")).get("column", "")
            except Exception:  # noqa: BLE001
                col = ""
        return outline_for(col)

    def style_lint(self) -> dict[str, Any]:
        rc, so, se = run([
            str(PY), str(SCRIPTS / "style_lint.py"),
            "--article", str(self.article), "--outline", str(self.outline_path()),
        ])
        r = tail_json(so)
        return {
            "status": r.get("status"),
            "blocking_count": r.get("blocking_count", 0),
            "blocking": r.get("blocking", [])[:8],
            "warning_count": r.get("warning_count", 0),
            "highlight": r.get("highlight"),
        }

    def render(self) -> dict[str, Any]:
        rc, so, se = run([
            str(PY), str(SCRIPTS / "render_template.py"),
            "--article", str(self.article), "--template", str(TEMPLATE),
            "--outline", str(self.outline_path()), "--out", str(self.html),
        ])
        r = tail_json(so)
        r["rc"] = rc
        if se:
            r["stderr"] = se[-300:]
        return r

    def meta(self) -> dict[str, str]:
        """标题/作者/摘要按固定规则推导，不依赖稿件里写了什么。
        标题 = {栏目}——{品牌+型号}；作者 = 步界社；摘要 = 测评{品牌+型号}
        """
        a = json.loads(self.article.read_text(encoding="utf-8"))
        shoe = (a.get("shoe") or "").strip() or self.d.name
        column = (a.get("column") or "").strip()
        if "篮球" in column or "球鞋" in column:
            column = "篮球鞋篇"
        else:
            column = "跑鞋篇"
        album = "球鞋" if column == "篮球鞋篇" else "跑鞋"
        return {"title": f"{column}——{shoe}", "author": "步界社",
                "digest": f"测评{shoe}", "album": album}

    def push_draft(self) -> dict[str, Any]:
        a = json.loads(self.article.read_text(encoding="utf-8"))
        m = self.meta()
        rc, so, se = run([
            str(PY), str(SCRIPTS / "mp_draft.py"), "--timeout", "300", "draft",
            "--html", str(self.html), "--save", "--close", "--headless",
            "--title", m["title"], "--author", m["author"],
            "--digest", m["digest"], "--album", m["album"],
            *(["--cover", str(self.d / "封面.png")] if (self.d / "封面.png").exists() else []),
            # 封面与发表仍由用户自己处理
        ], timeout=1200)
        r = tail_json(so)
        r["rc"] = rc
        if se:
            r["stderr"] = se[-300:]
        return r


ROOT = ROOT_ASSETS


def resolve_workdir(shoe: str) -> tuple[Path, bool]:
    """按鞋款名找工作目录；返回 (目录, 是否已有稿件)。名字模糊匹配已有文件夹。"""
    shoe = (shoe or "").strip()
    if not shoe:
        return WORKDIR, (WORKDIR / "article.json").exists()
    key = re.sub(r"[\s\-_°%]", "", shoe).lower()
    if ROOT.exists():
        for d in sorted(x for x in ROOT.iterdir() if x.is_dir()):
            if re.sub(r"[\s\-_°%]", "", d.name).lower() == key:
                return d, (d / "article.json").exists()
        for d in sorted(x for x in ROOT.iterdir() if x.is_dir()):
            n = re.sub(r"[\s\-_°%]", "", d.name).lower()
            if key and (key in n or n in key):
                return d, (d / "article.json").exists()
    return ROOT / shoe, False


PIPE = Pipeline(WORKDIR)

# ---- 公众号后台登录 ----
LOGIN: dict[str, Any] = {"running": False, "done": False, "ok": False, "msg": "未开始"}


def login_ok(timeout: int = 60) -> bool:
    """快速判断公众号后台登录态是否还有效。"""
    rc, so, _ = run([str(PY), str(SCRIPTS / "mp_draft.py"),
                     "--timeout", str(timeout), "check"], timeout=timeout + 60)
    return bool(tail_json(so).get("logged_in"))


def do_login() -> None:
    """弹窗让用户扫码，登录态存本机 profile。"""
    LOGIN.update(running=True, done=False, ok=False, msg="窗口已弹出，请用微信扫码…")
    try:
        rc, so, se = run([str(PY), str(SCRIPTS / "mp_draft.py"),
                          "--timeout", "300", "login"], timeout=400)
        r = tail_json(so)
        LOGIN["ok"] = r.get("status") == "ok"
        LOGIN["msg"] = "登录成功，可以重新点生成" if LOGIN["ok"] else \
                       f"登录未完成：{r.get('error') or se[-120:] or '扫码超时'}"
    except Exception as exc:  # noqa: BLE001
        LOGIN["msg"] = f"登录失败：{str(exc)[:120]}"
    LOGIN.update(running=False, done=True)


# ---- 存草稿（后台执行 + 进度）----
DRAFT: dict[str, Any] = {"running": False, "stage": "未开始", "done": False,
                         "ok": False, "result": {}, "error": ""}


def do_draft() -> None:
    DRAFT.update(running=True, stage="打开公众号后台…", done=False, ok=False,
                 result={}, error="")
    try:
        DRAFT["stage"] = "设置封面、合集、原创声明、创作来源，然后保存草稿"
        r = PIPE.push_draft()
        DRAFT["result"] = r
        DRAFT["ok"] = bool(r.get("saved_draft"))
        if not DRAFT["ok"]:
            DRAFT["error"] = r.get("error") or r.get("status") or "未确认保存"
    except Exception as exc:  # noqa: BLE001
        DRAFT["error"] = str(exc)[:200]
    DRAFT.update(running=False, done=True,
                 stage="完成" if DRAFT["ok"] else "未确认")


# ---- 生成任务（后台执行 + 实时进度）----
GEN: dict[str, Any] = {"running": False, "pct": 0, "stage": "未开始",
                       "steps": [], "done": False, "ok": False, "error": "",
                       "need_fields": []}


def gen_step(name: str, ok: bool, detail: Any = None) -> None:
    GEN["steps"].append({"name": name, "ok": ok, "detail": detail})


# ---- 写稿（调 kiro-cli，复用本机订阅）----
WRITE: dict[str, Any] = {"running": False, "pct": 0, "msg": "未开始", "done": False,
                         "error": "", "shoe": ""}


def do_write(shoe: str, column: str) -> None:
    WRITE.update(running=True, pct=0, msg="准备…", done=False, error="", shoe=shoe)
    try:
        proc = subprocess.Popen(
            [str(PY), str(SCRIPTS / "write_article.py"), "--shoe", shoe, "--column", column],
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, bufsize=1,
            errors="replace", env=ENV)
        last = ""
        for line in proc.stdout or []:
            m = re.match(r"PROGRESS (\d+) (.+)", line.strip())
            if m:
                WRITE.update(pct=int(m.group(1)), msg=m.group(2))
            else:
                last = line.strip()[:400] or last
        proc.wait(timeout=3000)
        if proc.returncode != 0:
            detail = ""
            try:
                j = json.loads(last[last.rfind("{"):]) if "{" in last else {}
                if j.get("status") == "service_unavailable":
                    detail = j.get("error", "")
                else:
                    probs = j.get("problems") or []
                    detail = "；".join(probs) if probs else (j.get("error") or "")
            except Exception:  # noqa: BLE001
                detail = last[:160]
            WRITE["error"] = f"写稿未完成：{detail or '未知原因'}"
    except Exception as exc:  # noqa: BLE001
        WRITE["error"] = str(exc)[:200]
    WRITE.update(running=False, done=True, pct=100)


# ---- 热度搜索（后台线程 + 进度轮询）----
SEARCH: dict[str, Any] = {"running": False, "pct": 0, "msg": "未开始", "done": False, "error": ""}


def do_search() -> None:
    SEARCH.update(running=True, pct=0, msg="启动搜索…", done=False, error="")
    try:
        proc = subprocess.Popen(
            [str(PY), str(SCRIPTS / "hot_shoes.py"), "--out", str(CANDS), "--limit", "5"],
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, bufsize=1,
            errors="replace", env=ENV)
        for line in proc.stdout or []:
            m = re.match(r"PROGRESS (\d+) (.+)", line.strip())
            if m:
                SEARCH.update(pct=int(m.group(1)), msg=m.group(2))
        proc.wait(timeout=600)
        if proc.returncode != 0:
            SEARCH["error"] = f"搜索脚本退出码 {proc.returncode}"
    except Exception as exc:  # noqa: BLE001
        SEARCH["error"] = str(exc)[:200]
    SEARCH.update(running=False, done=True, pct=100)


UI = Path(__file__).resolve().parent / "index.html"


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, fmt, *args):  # noqa: A003, ANN001
        sys.stderr.write("[app] " + fmt % args + "\n")

    def _send(self, code: int, body: bytes, ctype: str) -> None:
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _json(self, obj: Any, code: int = 200) -> None:
        self._send(code, json.dumps(obj, ensure_ascii=False).encode("utf-8"),
                   "application/json; charset=utf-8")

    @property
    def route(self) -> str:
        """只取路径，忽略 ?t=… 这类查询参数，否则精确匹配会掉到 404。"""
        return self.path.split("?", 1)[0]

    def do_GET(self) -> None:  # noqa: N802
        if self.route in ("/", "/index.html"):
            if not UI.exists():
                self._send(500, b"index.html missing", "text/plain; charset=utf-8")
                return
            self._send(200, UI.read_bytes(), "text/html; charset=utf-8")
            return
        if self.route in ("/logo.png", "/favicon.ico"):
            if LOGO.exists():
                self._send(200, LOGO.read_bytes(), "image/png")
            else:
                self._send(404, b"logo missing", "text/plain")
            return
        if self.route == "/api/login/status":
            self._json(LOGIN)
            return
        if self.route == "/api/draft/status":
            self._json(DRAFT)
            return
        if self.route == "/api/generate/status":
            self._json(GEN)
            return
        if self.route == "/api/write/status":
            self._json(WRITE)
            return
        if self.route == "/api/search/status":
            self._json(SEARCH)
            return
        if self.route == "/api/candidates":
            data = {"candidates": []}
            if CANDS.exists():
                data = json.loads(CANDS.read_text(encoding="utf-8"))
            out = []
            for c in data.get("candidates", []):
                wd, has = resolve_workdir(c.get("name", ""))
                out.append({**c, "has_article": has, "workdir": str(wd)})
            # 素材盘里已有稿件但候选表没列的，也补进来
            listed = {re.sub(r"[\s\-_°%]", "", c["name"]).lower() for c in out}
            if ROOT.exists():
                for d in sorted(x for x in ROOT.iterdir() if x.is_dir()):
                    if not (d / "article.json").exists():
                        continue
                    if re.sub(r"[\s\-_°%]", "", d.name).lower() in listed:
                        continue
                    a = json.loads((d / "article.json").read_text(encoding="utf-8"))
                    out.append({"name": a.get("shoe", d.name), "column": a.get("column", ""),
                                "hot": "素材盘里已有稿件", "has_article": True, "workdir": str(d)})
            self._json({"updated": data.get("updated", ""), "candidates": out})
            return
        if self.route == "/api/context":
            a = {}
            if PIPE.article.exists():
                a = json.loads(PIPE.article.read_text(encoding="utf-8"))
            self._json({
                "shoe": a.get("shoe", ""),
                "title": a.get("title", ""),
                "column": a.get("column", ""),
                "slots": [{"num": n, "label": l, "section": s} for n, l, s in IMG_SLOTS],
                "problems": PIPE.check_env(),
                "workdir": str(WORKDIR),
                "logo": LOGO.exists(),
                "shoes": sorted(
                    d.name for d in ROOT.iterdir()
                    if ROOT.exists() and d.is_dir() and (d / "article.json").exists()
                ) if ROOT.exists() else [],
            })
            return
        if self.route == "/api/cover/preview":
            f = PIPE.d / "封面.png"
            if f.exists():
                self._send(200, f.read_bytes(), "image/png")
            else:
                self._send(404, b"no cover", "text/plain")
            return
        if self.route == "/api/preview":
            if PIPE.html.exists():
                self._send(200, PIPE.html.read_bytes(), "text/html; charset=utf-8")
            else:
                self._send(404, b"not rendered yet", "text/plain; charset=utf-8")
            return
        self._send(404, b"not found", "text/plain; charset=utf-8")

    def do_POST(self) -> None:  # noqa: N802
        n = int(self.headers.get("Content-Length") or 0)
        try:
            payload = json.loads(self.rfile.read(n) or b"{}")
        except Exception as exc:  # noqa: BLE001
            self._json({"error": f"bad json: {exc}"}, 400)
            return

        if self.route == "/api/generate":
            if not GEN["running"]:
                threading.Thread(target=do_generate, args=(payload,), daemon=True).start()
            self._json({"started": True})
            return
        if self.route == "/api/write":
            shoe = str(payload.get("shoe", "")).strip()
            column = str(payload.get("column", "")).strip() or "跑鞋篇"
            if not shoe:
                self._json({"error": "缺少鞋款名"}, 400)
                return
            if not WRITE["running"]:
                threading.Thread(target=do_write, args=(shoe, column), daemon=True).start()
            self._json({"started": True})
            return
        if self.route == "/api/search":
            if not SEARCH["running"]:
                threading.Thread(target=do_search, daemon=True).start()
            self._json({"started": True})
            return
        if self.route == "/api/cover":
            global PIPE
            shoe = str(payload.get("shoe", "")).strip()
            wd, _ = resolve_workdir(shoe)
            wd.mkdir(parents=True, exist_ok=True)
            PIPE = Pipeline(wd)
            items = payload.get("images", [])
            if not items:
                self._json({"status": "no_image", "error": "需要第一张图（侧视图）"}, 200)
                return
            paths = PIPE.save_images(items[:1])
            self._json(PIPE.make_cover(paths[0], shoe))
            return
        if self.route == "/api/login":
            if not LOGIN["running"]:
                threading.Thread(target=do_login, daemon=True).start()
            self._json({"started": True})
            return
        if self.route == "/api/draft":
            if not DRAFT["running"]:
                threading.Thread(target=do_draft, daemon=True).start()
            self._json({"started": True})
            return
        self._json({"error": "unknown endpoint"}, 404)


def do_generate(p: dict[str, Any]) -> None:
    """后台跑完整生成流程：写稿（若无）→ 价格 → 图片上传 → 核查 → 文风 → 渲染。"""
    global PIPE
    GEN.update(running=True, pct=0, stage="准备", steps=[], done=False, ok=False,
               error="", need_fields=[], need_login=False)
    try:
        shoe = str(p.get("shoe", "")).strip()
        column = str(p.get("column", "")).strip() or "跑鞋篇"
        wd, has_article = resolve_workdir(shoe)
        PIPE = Pipeline(wd, column)
        gen_step("选题", True, f"{shoe} → {wd}")
        GEN.update(pct=4, stage="选题确认")

        # 先确认后台登录态。过期就直接弹扫码窗口并等你扫完，不用你自己去处理。
        if not p.get("dry_run"):
            GEN.update(pct=3, stage="检查公众号后台登录态")
            if not login_ok():
                GEN.update(stage="登录态过期，已弹出扫码窗口，请用微信扫码")
                gen_step("登录检查", False, "登录态过期，正在弹窗等你扫码…")
                do_login()
                if not LOGIN["ok"]:
                    gen_step("扫码登录", False, LOGIN["msg"])
                    GEN.update(running=False, done=True, ok=False, pct=100, need_login=True)
                    return
                gen_step("扫码登录", True, "登录成功，继续")
            else:
                gen_step("登录检查", True, "登录态有效")

        if not has_article:
            GEN.update(pct=6, stage="正在搜数据并写稿，这一步最久")
            do_write(shoe, column)
            if WRITE.get("error"):
                gen_step("写稿", False, WRITE["error"])
                GEN.update(running=False, done=True, ok=False, pct=100)
                return
            gen_step("写稿", True, "已生成 article.json 与 claims.json")
        else:
            gen_step("写稿", True, "已有稿件，跳过")
        GEN.update(pct=55, stage="校验环境")

        miss = PIPE.missing_fields()
        fills = p.get("fills") or {}
        if fills:
            filled = PIPE.fill_fields(fills)
            if filled["errors"]:
                gen_step("补填字段", False, "；".join(x["error"] for x in filled["errors"]))
                GEN.update(running=False, done=True, ok=False, pct=100,
                           stage="输入格式不对，请重新填写", need_fields=filled["errors"])
                return
            gen_step("补填字段", True, f"已补 {filled['done']}")
            miss = PIPE.missing_fields()
        if miss:
            GEN.update(running=False, done=True, ok=False, pct=100,
                       stage="等你补填", need_fields=miss)
            gen_step("字段检查", False,
                     "这些信息网上没搜到，需要你补上：" + "、".join(m["label"] for m in miss))
            return

        problems = PIPE.check_env()
        gen_step("环境检查", not problems, problems or f"工作目录 {PIPE.d}")
        if problems:
            GEN.update(running=False, done=True, ok=False, pct=100)
            return

        low, high = str(p.get("low", "")).strip(), str(p.get("high", "")).strip()
        if not (low.isdigit() and high.isdigit()) or int(low) > int(high):
            gen_step("价格区间", False, "上下区间必须是数字且低价不大于高价")
            GEN.update(running=False, done=True, ok=False, pct=100)
            return
        val = PIPE.set_price(low, high)
        PIPE.register_price_claim(low, high)
        gen_step("写入价格区间", True, val)
        dt = PIPE.set_publish_date(str(p.get("date", "")).strip())
        gen_step("写入发布日期", True, dt)
        GEN.update(pct=62, stage="处理图片")

        items = p.get("images", [])
        if len(items) != 4:
            gen_step("图片检查", False, f"需要 4 张，收到 {len(items)}")
            GEN.update(running=False, done=True, ok=False, pct=100)
            return
        paths = PIPE.save_images(items)
        gen_step("保存图片", True, [x.name for x in paths])
        cover = PIPE.d / "封面.png"
        upload_list = paths + ([cover] if cover.exists() else [])

        if p.get("dry_run"):
            gen_step("上传素材库", True, "试运行：跳过上传")
        else:
            GEN.update(pct=70, stage="上传素材库")
            up = PIPE.upload(upload_list)
            got = {}
            for r in up.get("result", {}).get("results", []):
                if r.get("url"):
                    got[Path(r.get("local", "")).stem] = r["url"]
            need = len(upload_list)
            if len(got) < need:
                expired = len(got) == 0     # 一张都没成功，基本是登录态失效
                gen_step("上传素材库", False,
                         {"成功": len(got), "应传": need,
                          "提示": ("公众号后台登录态过期了，点下面的「重新扫码登录」"
                                   if expired else "部分图片没拿到地址，重试一次")})
                GEN.update(running=False, done=True, ok=False, pct=100,
                           need_login=expired)
                return
            gen_step("上传素材库", True,
                     f"{len(got)} 张（含封面）" if (PIPE.d / "封面.png").exists() else f"{len(got)} 张")
            # 只把 01–04 回填到正文，封面不进正文
            PIPE.set_image_urls({k: v for k, v in got.items() if k in ("01", "02", "03", "04")})
            gen_step("回填图片地址", True, sorted(got))

        GEN.update(pct=82, stage="事实核查")
        fc = PIPE.fact_check()
        gen_step("事实核查", fc["blocking_count"] == 0, fc)
        if fc["blocking_count"]:
            GEN.update(running=False, done=True, ok=False, pct=100)
            return

        GEN.update(pct=90, stage="文风与格式检查")
        sl = PIPE.style_lint()
        gen_step("文风与格式检查", sl["blocking_count"] == 0, sl)
        if sl["blocking_count"]:
            GEN.update(running=False, done=True, ok=False, pct=100)
            return

        GEN.update(pct=96, stage="排版渲染")
        rd = PIPE.render()
        ok = str(rd.get("status", "")).startswith("ok")
        gen_step("排版渲染", ok, rd)
        rm = PIPE.cleanup()
        gen_step("清理临时图片", True, f"删除 {len(rm)} 个")
        GEN.update(running=False, done=True, ok=ok, pct=100, stage="完成" if ok else "失败")
    except Exception as exc:  # noqa: BLE001
        GEN.update(error=str(exc)[:300], running=False, done=True, ok=False, pct=100)


def already_running() -> bool:
    """端口被占时，先确认是不是自己的另一份实例在跑。"""
    try:
        import urllib.request

        with urllib.request.urlopen(f"http://{HOST}:{PORT}/api/context", timeout=2) as r:
            return r.status == 200
    except Exception:  # noqa: BLE001
        return False


class Server(ThreadingHTTPServer):
    allow_reuse_address = True
    daemon_threads = True


def main() -> int:
    try:
        srv = Server((HOST, PORT), Handler)
    except OSError as exc:
        if already_running():
            print(f"已有实例在 {HOST}:{PORT} 运行，本次直接复用，不再另起。")
            return 0
        print(f"端口 {PORT} 被别的程序占用了：{exc}")
        return 1
    url = f"http://{HOST}:{PORT}"
    print(f"步界社公众号生成器已启动：{url}")
    print("按 Ctrl+C 结束")
    if "--no-browser" not in sys.argv:
        threading.Timer(1.0, lambda: webbrowser.open(url)).start()
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        print("\n已停止")
    return 0


if __name__ == "__main__":
    sys.exit(main())
