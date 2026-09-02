#!/usr/bin/env python3
"""把渲染好的 HTML 灌进公众号后台编辑器，存成草稿。

安全边界（写死在脚本里，不提供开关）：
  · 只填内容、只保存草稿
  · 绝不点击「发表」「群发」「定时发送」
  · 最后一步默认把浏览器留在编辑器页面，由你自己肉眼确认

登录态保存在 ~/.kiro/mp-browser-profile，首次运行请在弹出的 Chrome 里扫码登录。
不读取、不打印、不上传任何 Cookie。

用法:
  mp_draft.py login
  mp_draft.py upload --image cover.png --image p1.png --out uploaded.json
  mp_draft.py draft --title "标题" --author "作者" --digest "摘要" --html article.html
  mp_draft.py draft --title T --html a.html --save        # 额外尝试点「保存为草稿」
"""
from __future__ import annotations

import argparse
import fcntl
import json
import re
import sys
import time
import unicodedata
from contextlib import contextmanager
from pathlib import Path
from typing import Any

PROFILE_DIR = Path.home() / ".kiro" / "mp-browser-profile"
CHROME = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
HOME = "https://mp.weixin.qq.com/"
FORBIDDEN_BUTTON_RX = re.compile(r"(发表|群发|发送|定时)")


def need_playwright():
    try:
        from playwright.sync_api import sync_playwright  # noqa: PLC0415

        return sync_playwright
    except ImportError:
        print(
            json.dumps(
                {
                    "status": "environment_error",
                    "error": "缺少 playwright。在 skill 目录执行："
                    "python3 -m venv .venv && .venv/bin/pip install -r requirements.txt",
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        sys.exit(6)


@contextmanager
def profile_lock(timeout: int = 600):
    """同一个 Chrome 配置目录只允许一个会话，否则 Chrome 会因 ProcessSingleton 冲突中止。"""
    PROFILE_DIR.mkdir(parents=True, exist_ok=True)
    lock = PROFILE_DIR.parent / "mp-browser-profile.lock"
    fh = open(lock, "w")
    deadline = time.time() + timeout
    while True:
        try:
            fcntl.flock(fh, fcntl.LOCK_EX | fcntl.LOCK_NB)
            break
        except OSError:
            if time.time() > deadline:
                fh.close()
                raise RuntimeError("浏览器会话被占用超时：另一个任务正在使用公众号后台，请稍后再试")
            time.sleep(2)
    try:
        yield
    finally:
        try:
            fcntl.flock(fh, fcntl.LOCK_UN)
        finally:
            fh.close()


def open_ctx(pw, headless: bool = False):
    PROFILE_DIR.mkdir(parents=True, exist_ok=True)
    return pw.chromium.launch_persistent_context(
        user_data_dir=str(PROFILE_DIR),
        executable_path=CHROME if Path(CHROME).exists() else None,
        headless=headless,
        viewport={"width": 1500, "height": 950},
        locale="zh-CN",
    )


def wait_login(page, timeout: int = 300) -> str:
    """返回后台 token；未登录时等用户扫码。"""
    page.goto(HOME, wait_until="domcontentloaded", timeout=60000)
    deadline = time.time() + timeout
    while time.time() < deadline:
        m = re.search(r"[?&]token=(\d+)", page.url)
        if m:
            return m.group(1)
        try:
            page.wait_for_timeout(2000)
        except Exception:  # noqa: BLE001
            break
        # 已登录但停在首页时点一下首页入口
        if "/cgi-bin/home" in page.url:
            m = re.search(r"[?&]token=(\d+)", page.url)
            if m:
                return m.group(1)
    raise RuntimeError("等待登录超时：请在浏览器里扫码登录公众号后台后重试")


def cmd_login(args: argparse.Namespace) -> int:
    sp = need_playwright()
    with profile_lock(), sp() as pw:
        ctx = open_ctx(pw, headless=False)
        page = ctx.pages[0] if ctx.pages else ctx.new_page()
        try:
            token = wait_login(page, args.timeout)
        except RuntimeError as exc:
            ctx.close()
            print(json.dumps({"status": "login_required", "error": str(exc)}, ensure_ascii=False))
            return 8
        print(json.dumps({"status": "ok", "token": token, "profile": str(PROFILE_DIR)},
                         ensure_ascii=False, indent=2))
        ctx.close()
    return 0


def cmd_upload(args: argparse.Namespace) -> int:
    """把本地图片传到素材库并拿回 mmbiz 地址。

    素材库列表页的 img 标签读不到 mmbiz 地址（懒加载/背景图），所以改为监听上传接口的
    JSON 回包，从里面取 cdn_url —— 这是实测可靠的方式。
    """
    sp = need_playwright()
    files = [str(Path(p).expanduser().resolve()) for p in args.image]
    missing = [f for f in files if not Path(f).exists()]
    if missing:
        print(json.dumps({"status": "input_error", "missing": missing}, ensure_ascii=False))
        return 2

    captured: list[str] = []

    def on_resp(r):  # noqa: ANN001
        if not re.search(r"(filetransfer|uploadimg|cgi-bin/upload)", r.url):
            return
        try:
            if "json" not in (r.headers or {}).get("content-type", ""):
                return
            body = json.dumps(r.json(), ensure_ascii=False)
        except Exception:  # noqa: BLE001
            return
        for m in re.finditer(r'"(?:cdn_url|url)"\s*:\s*"(https?://mmbiz\.qpic\.cn/[^"]+)"', body):
            captured.append(m.group(1).replace("\\/", "/"))

    results: list[dict[str, Any]] = []
    with profile_lock(), sp() as pw:
        ctx = open_ctx(pw, headless=bool(getattr(args, "headless", False)))
        page = ctx.pages[0] if ctx.pages else ctx.new_page()
        page.on("response", on_resp)
        token = wait_login(page, args.timeout)
        page.goto(
            f"https://mp.weixin.qq.com/cgi-bin/filepage?token={token}&lang=zh_CN"
            "&type=2&begin=0&count=20",
            wait_until="domcontentloaded", timeout=60000)
        page.wait_for_timeout(4000)

        fp = (f"https://mp.weixin.qq.com/cgi-bin/filepage?token={token}&lang=zh_CN"
              "&type=2&begin=0&count=20")

        group = str(getattr(args, "group", "") or "").strip()
        group_state = "未指定"
        if group:
            group_state = ensure_group(page, group)
        for f in files:
            n0 = len(captured)
            sent = False
            for attempt in range(3):
                try:
                    page.wait_for_selector("input[type=file]", timeout=20000, state="attached")
                    for inp in page.query_selector_all("input[type=file]"):
                        try:
                            inp.set_input_files(f)
                            sent = True
                            break
                        except Exception:  # noqa: BLE001
                            continue
                    if sent:
                        break
                except Exception:  # noqa: BLE001
                    pass
                # 页面可能因上传后跳转导致上下文失效，重进列表页再试
                try:
                    page.goto(fp, wait_until="domcontentloaded", timeout=60000)
                    page.wait_for_timeout(3000)
                except Exception:  # noqa: BLE001
                    page.wait_for_timeout(2000)
            url = None
            for _ in range(20):          # 最多等 20 秒收回包
                page.wait_for_timeout(1000)
                if len(captured) > n0:
                    url = captured[n0]
                    break
            results.append({"local": f, "status": "ok" if url else "needs_manual", "url": url})
        ctx.close()

    ok = all(r["status"] == "ok" for r in results)
    payload = {
        "status": "ok" if ok else "partial",
        "group": group,
        "group_state": group_state,
        "results": results,
        "hint": "" if ok else "没拿到地址的图片请在后台素材库手动上传后回填 mmbiz 地址",
    }
    if args.out:
        Path(args.out).expanduser().write_text(
            json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0 if ok else 7


def ensure_group(page, name: str) -> str:
    """确保素材库里有名为 name 的分组并选中它。失败不阻断上传。"""
    try:
        # 已存在就直接点
        exist = page.locator(f'text="{name}"').filter(visible=True)
        if exist.count():
            try:
                exist.first.click()
                page.wait_for_timeout(1500)
                return "已选中已有分组"
            except Exception:  # noqa: BLE001
                pass
        btn = page.locator("a.weui-desktop-btn_add-img-group").filter(visible=True).first
        btn.wait_for(state="visible", timeout=8000)
        btn.click()
        page.wait_for_timeout(1200)
        box = page.locator('input[type=text]:visible').last
        box.fill(name)
        page.wait_for_timeout(500)
        for label in ("确定", "确认", "保存"):
            try:
                page.locator(f'button:has-text("{label}")').filter(visible=True).first.click()
                break
            except Exception:  # noqa: BLE001
                continue
        page.wait_for_timeout(2500)
        return "已新建分组"
    except Exception as exc:  # noqa: BLE001
        return f"分组处理失败（不影响上传）：{str(exc)[:80]}"


def collect_cdn_urls(page) -> list[str]:
    try:
        return page.eval_on_selector_all(
            "img",
            "els => els.map(e => e.getAttribute('src') || e.getAttribute('data-src') || '')"
            ".filter(s => s.includes('mmbiz.qpic.cn'))",
        )
    except Exception:  # noqa: BLE001
        return []


# 公众号新版编辑器是 ProseMirror（contenteditable），textarea#title 是隐藏占位元素。
# 直接写 innerHTML 或往隐藏 textarea 塞值都不会进编辑器的数据模型，保存出来是空的。
# 正确做法：标题用键盘输入，正文派发 paste 事件让 ProseMirror 自己解析 HTML。
PASTE_JS = """(html) => {
  const els = [...document.querySelectorAll('div.ProseMirror')].filter(e => e.offsetParent);
  const body = els[1];
  if (!body) return { ok: false, reason: 'body_editor_not_found', editors: els.length };
  body.focus();
  const dt = new DataTransfer();
  dt.setData('text/html', html);
  dt.setData('text/plain', '');
  body.dispatchEvent(new ClipboardEvent('paste', { clipboardData: dt, bubbles: true, cancelable: true }));
  return { ok: true };
}"""


def set_original(page, author: str = "步界社") -> str:
    """原创声明：文字原创 + 作者 + 白名单留空 + 快捷转载保持开启 + 同意协议 → 确定。"""
    step = "打开原创"
    try:
        page.locator("#js_original").first.click(timeout=15000)
        page.wait_for_timeout(5000)
        dlg = page.locator(".weui-desktop-dialog").filter(visible=True).last

        step = "选文字原创"
        try:
            dlg.locator('text="文字原创"').first.click(timeout=6000)
            page.wait_for_timeout(1200)
        except Exception:  # noqa: BLE001
            pass

        step = "填作者"
        try:
            box = dlg.locator("input.weui-desktop-form__input").filter(visible=True).first
            box.fill(author)
            page.wait_for_timeout(800)
        except Exception:  # noqa: BLE001
            pass

        step = "勾选协议"
        try:
            dlg.locator('text=/我已阅读并同意/').first.click(timeout=6000)
            page.wait_for_timeout(1000)
        except Exception:  # noqa: BLE001
            pass

        step = "确定"
        dlg.locator('button:has-text("确定")').filter(visible=True).first.click(timeout=10000)
        page.wait_for_timeout(4000)
        return "已声明原创（文字原创，快捷转载保持开启）"
    except Exception as exc:  # noqa: BLE001
        return f"原创声明失败于[{step}]：{str(exc)[:60]}"


def set_claim_source(page, text: str = "个人观点，仅供参考") -> str:
    """创作来源选「个人观点，仅供参考」。"""
    try:
        page.locator("#js_claim_source_area").first.click(timeout=15000)
        page.wait_for_timeout(4000)
        dlg = page.locator(".weui-desktop-dialog").filter(visible=True).last
        for kw in ("个人观点", text):
            try:
                dlg.locator(f'text=/{kw}/').first.click(timeout=5000)
                page.wait_for_timeout(1000)
                break
            except Exception:  # noqa: BLE001
                continue
        try:
            dlg.locator('button:has-text("确定")').filter(visible=True).first.click(timeout=8000)
            page.wait_for_timeout(3000)
        except Exception:  # noqa: BLE001
            pass
        return "创作来源：个人观点，仅供参考"
    except Exception as exc:  # noqa: BLE001
        return f"创作来源设置失败：{str(exc)[:60]}"


def set_cover(page, cover: Path) -> str:
    """设文章封面。前提：封面已经上传到素材库（生成流程里一起传的）。
    封面区 → 从图片库选择 → 按文件名选中 → 下一步 → 确定。
    """
    step = "打开封面区"
    name = cover.name
    cropped: list[str] = []

    def _on_crop(r):  # noqa: ANN001
        if "cropimage" in r.url:
            try:
                body = r.text()
                if '"cdnurl"' in body and '"ret":0' in body:
                    cropped.append(body[:80])
            except Exception:  # noqa: BLE001
                pass

    try:
        page.on("response", _on_crop)
        page.locator(".js_cover_btn_area").first.click(timeout=20000)
        page.wait_for_timeout(3000)
        step = "从图片库选择"
        page.locator("a.js_imagedialog").filter(visible=True).first.click(timeout=15000)
        page.wait_for_timeout(9000)

        step = f"按文件名选中 {name}"
        hit = page.evaluate("""(name)=>{
          const items=[...document.querySelectorAll('.weui-desktop-img-picker__item')];
          for(const it of items){
            const t=it.querySelector('.weui-desktop-img-picker__img-title');
            if(t && t.innerText.trim()===name){ it.click(); return true; }
          }
          return false;
        }""", name)
        if not hit:
            return f"素材库里找不到 {name}，需要先上传"
        page.wait_for_timeout(2500)

        # 选中 → 下一步 → 进「编辑封面」裁剪页（2.35:1 / 1:1）→ 确认
        step = "下一步"
        page.locator('button:has-text("下一步")').filter(visible=True).first.click(timeout=10000)
        page.wait_for_timeout(6000)
        step = "裁剪页确认"
        page.locator('button:has-text("确认")').filter(visible=True).first.click(timeout=10000)
        page.wait_for_timeout(5000)

        step = "关闭残留弹窗"
        for _ in range(3):
            try:
                d = page.locator(".weui-desktop-dialog").filter(visible=True)
                if not d.count():
                    break
                d.last.locator('button:has-text("确定"), button:has-text("完成"), '
                               'button:has-text("取消")').first.click(timeout=3000)
                page.wait_for_timeout(2500)
            except Exception:  # noqa: BLE001
                break

        # 以裁剪接口回包为准。编辑器封面框的文案在无头模式下不刷新，
        # 用它判断会误报「未贴上」——实际封面已经绑定成功。
        return ("已设置封面" if cropped
                else "封面已选中，但没收到裁剪回包，建议去后台确认一下")
    except Exception as exc:  # noqa: BLE001
        return f"设封面失败于[{step}]（不影响存草稿）：{str(exc)[:60]}"


def pick_album(page, name: str) -> str:
    """按名字选合集。你号里的合集名是「跑鞋」「球鞋」，不是文章标题前缀。"""
    step = "打开合集"
    try:
        page.locator(".js_article_tags_label").first.click(timeout=20000)
        page.wait_for_timeout(5000)
        step = "点选择框"
        page.locator('input[placeholder="请选择合集"]').first.click(timeout=15000)
        page.wait_for_timeout(3500)
        step = f"选项 {name}"
        page.locator("li.select-opt-li", has_text=name).first.click(timeout=15000)
        page.wait_for_timeout(2000)
        step = "点确认"
        page.locator('.weui-desktop-dialog button:has-text("确认")').last.click(timeout=15000)
        page.wait_for_timeout(3000)
        return f"已选合集{name}"
    except Exception as exc:  # noqa: BLE001
        return f"选合集失败于[{step}]（不影响存草稿）：{str(exc)[:60]}"


def draft_exists(page, token: str, title: str, ctx=None) -> bool:
    """以草稿箱列表为准核验，不轻信按钮点击或接口回包。"""
    # 保存后离开编辑器可能弹「确认离开」，不处理会让跳转卡住
    try:
        page.on("dialog", lambda d: d.accept())
    except Exception:  # noqa: BLE001
        pass
    def norm(x: str) -> str:
        """破折号、空格、大小写在页面渲染后可能不一致，比对前统一。"""
        x = unicodedata.normalize("NFKC", x)
        x = re.sub(r"[—–\-—\s·]+", "", x)
        return x.lower()

    key = norm(title)[:14]
    # 编辑器页保存后状态残留会影响跳转后的渲染，另开一个标签页核验
    probe = page
    opened = False
    if ctx is not None:
        try:
            probe = ctx.new_page()
            opened = True
        except Exception:  # noqa: BLE001
            probe = page
    try:
        probe.goto(
            "https://mp.weixin.qq.com/cgi-bin/appmsg?t=media/appmsg_list&action=list_card"
            f"&begin=0&count=10&token={token}&lang=zh_CN&type=77",
            wait_until="domcontentloaded",
            timeout=60000,
        )
        # 草稿箱列表是前端渲染的，出现时间不稳定，轮询到出现为止
        for _ in range(15):
            probe.wait_for_timeout(2000)
            try:
                if key and key in norm(probe.inner_text("body")):
                    return True
            except Exception:  # noqa: BLE001
                continue
        return False
    except Exception as exc:  # noqa: BLE001
        print(f"核验草稿箱失败：{str(exc)[:120]}", file=sys.stderr)
        return False
    finally:
        if opened:
            try:
                probe.close()
            except Exception:  # noqa: BLE001
                pass


def cmd_draft(args: argparse.Namespace) -> int:
    sp = need_playwright()
    html = Path(args.html).expanduser().read_text(encoding="utf-8")
    local_imgs = re.findall(r'<img[^>]+src="(?!https?://)([^"]+)"', html)
    if local_imgs and not args.allow_local_images:
        print(json.dumps({"status": "refused",
                          "error": "HTML 里还有本地图片路径，先跑 upload 拿 mmbiz 地址。",
                          "local_images": local_imgs[:10]}, ensure_ascii=False, indent=2))
        return 9

    with profile_lock(), sp() as pw:
        ctx = open_ctx(pw, headless=bool(getattr(args, "headless", False)))
        page = ctx.pages[0] if ctx.pages else ctx.new_page()
        token = wait_login(page, args.timeout)
        url = args.editor_url or (
            "https://mp.weixin.qq.com/cgi-bin/appmsg?t=media/appmsg_edit_v2&action=edit"
            f"&isNew=1&type=77&createType=0&token={token}&lang=zh_CN"
        )
        page.goto(url, wait_until="load", timeout=90000)
        try:
            page.wait_for_selector("div.ProseMirror", timeout=60000)
        except Exception:
            ctx.close()
            print(json.dumps({"status": "editor_not_ready",
                              "error": "等不到 ProseMirror 编辑器"}, ensure_ascii=False, indent=2))
            return 10
        page.wait_for_timeout(8000)

        ed = page.locator("div.ProseMirror").filter(visible=True)
        filled: dict[str, Any] = {}
        if not args.content_only:
            if args.title:
                try:
                    ed.nth(0).click()
                    page.keyboard.type(args.title)
                    page.wait_for_timeout(800)
                    filled["title"] = args.title[:6] in ed.nth(0).inner_text()
                except Exception:
                    filled["title"] = False
            for name, sel, val in (("author", "input#author", args.author),
                                   ("digest", "textarea#js_description", args.digest)):
                if not val:
                    continue
                try:
                    page.fill(sel, val)
                    filled[name] = True
                except Exception:
                    filled[name] = False
        else:
            filled["skipped"] = "标题/作者/摘要留给用户"

        try:
            ed.nth(1).click()
        except Exception:
            pass
        res = page.evaluate(PASTE_JS, html)
        page.wait_for_timeout(5000)
        chars = 0
        try:
            chars = len(ed.nth(1).inner_text())
        except Exception:
            pass
        # 正文为空时公众号不会真正保存封面，所以封面与合集都放在贴完正文之后
        cover_state = "未指定"
        cv = getattr(args, "cover", "")
        if cv and Path(cv).expanduser().exists():
            cover_state = set_cover(page, Path(cv).expanduser())
        original_state = "未设置"
        if getattr(args, "original", False):
            original_state = set_original(page, args.author or "步界社")
        claim_state = "未设置"
        if getattr(args, "claim_source", False):
            claim_state = set_claim_source(page)

        album_state = "未指定"
        if getattr(args, "album", ""):
            album_state = pick_album(page, args.album)

        if not res.get("ok") or chars < 200:
            ctx.close()
            print(json.dumps({"status": "inject_failed", "detail": res, "content_chars": chars},
                             ensure_ascii=False, indent=2))
            return 11

        saved = False
        if args.save:
            try:
                page.click('button:has-text("保存为草稿")')
                page.wait_for_timeout(9000)
            except Exception as exc:  # noqa: BLE001
                print(f"点击保存失败: {exc}", file=sys.stderr)
            saved = draft_exists(page, token, args.title, ctx) if args.title else True


        print(json.dumps({
            "status": "ok" if (saved or not args.save) else "save_unverified",
            "editor_url": url,
            "filled": filled,
            "content_chars": chars,
            "album": album_state,
            "cover": cover_state,
            "original": original_state,
            "claim_source": claim_state,
            "saved_draft": saved,
            "verified_by": "草稿箱列表",
            "note": "脚本不会点发表/群发；封面、原创声明、话题标签仍需手动。",
        }, ensure_ascii=False, indent=2))
        if not args.close:
            try:
                input()
            except EOFError:
                pass
        ctx.close()
    return 0 if (saved or not args.save) else 12


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="公众号草稿推送")
    ap.add_argument("--timeout", type=int, default=300, help="等待扫码登录秒数")
    sub = ap.add_subparsers(dest="cmd", required=True)

    lg = sub.add_parser("login", help="首次扫码登录并缓存登录态")
    lg.set_defaults(func=cmd_login)

    up = sub.add_parser("upload", help="上传图片到素材库")
    up.add_argument("--image", action="append", required=True)
    up.add_argument("--out")
    up.add_argument("--keep-open", action="store_true")
    up.add_argument("--headless", action="store_true", help="不弹窗口（需已登录过一次）")
    up.add_argument("--group", default="", help="素材库分组名，例如 8")
    up.set_defaults(func=cmd_upload)

    dr = sub.add_parser("draft", help="填入编辑器")
    dr.add_argument("--title", default="")
    dr.add_argument("--author", default="")
    dr.add_argument("--digest", default="")
    dr.add_argument("--html", required=True)
    dr.add_argument("--editor-url", default="")
    dr.add_argument("--save", action="store_true", help="尝试点击「保存为草稿」")
    dr.add_argument("--close", action="store_true", help="完成后直接关闭浏览器")
    dr.add_argument("--allow-local-images", action="store_true")
    dr.add_argument("--content-only", action="store_true",
                    help="只贴正文，不填标题/作者/摘要（这些由用户自己在后台处理）")
    dr.add_argument("--headless", action="store_true",
                    help="不弹浏览器窗口（需已登录过一次）")
    dr.add_argument("--album", default="", help="合集名，跑鞋 或 球鞋")
    dr.add_argument("--cover", default="", help="封面图路径，会上传并设为文章封面")
    dr.add_argument("--original", action="store_true", help="声明原创（文字原创）")
    dr.add_argument("--claim-source", action="store_true", help="创作来源设为个人观点仅供参考")
    dr.set_defaults(func=cmd_draft)

    args = ap.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
