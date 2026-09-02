---
name: wechat-mp-publisher
description: '端到端生产公众号图文：选题 → 全网测评数据搜集（国内+海外）→ 得物二级市场配色价格 → 事实核查 → 按本号历史排版 1:1 复刻 HTML → 配图 → 灌入公众号后台存草稿。排版靠 extract_template.py 把历史文章的组件整段抠出来做占位符替换，不靠人工描述、不靠 CSS 泛化；正文里每个带单位的数字都必须在 claims.json 登记并通过 fact_check.py。当用户要写/发公众号文章，尤其是跑鞋/球鞋测评+价格类内容时使用。'
metadata:
  author: jackli
  display_name: 公众号图文生产
  version: 2.0.0
  tags:
    - 公众号
    - 内容生产
    - 事实核查
  requires:
    bins:
      - python3
    optional_env:
      - OPENAI_API_KEY
      - DASHSCOPE_API_KEY
      - ISTARSHINE_API_KEY
---

# 公众号图文生产

从"今天发什么"到"后台里躺着一篇可预览的草稿"。核心两件事：**排版原样复刻历史文章**，**数字必须可核验**。

当前已适配账号：**<你的公众号>**（秀米/135 模板号，栏目：跑鞋篇 / 篮球鞋篇）。

## 环境准备（首次一次）

```bash
cd ~/.kiro/skills/wechat-mp-publisher
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
```

后续 `python` 均指 `~/.kiro/skills/wechat-mp-publisher/.venv/bin/python`，命令都在 skill 目录下执行。
每篇文章一个工作目录 `~/mp-posts/<YYYYMMDD>-<slug>/`，产物全落在里面。

---

## Step 0 · 学格式

公众号后台首页要登录态，抓不到。用**已发布文章的公开分享链接**（`mp.weixin.qq.com/s/...`）。

**模板号走这条**（本号即是，外层渐变容器 + 白卡 + 圆圈编号组件，CSS 规则泛化不出来）：

```bash
python scripts/extract_template.py --url https://mp.weixin.qq.com/s/xxx \
  --out references/template_rdfz.json --outline-out references/outline_running.json
```

抠出 wrapper / header / marker（圆圈编号+章节名）/ body / sub_heading / paragraph / image /
highlight_positive / highlight_negative / footer 共 11 个组件，全部是原文片段 + 占位符。
已验证这些组件在三篇历史文章里**完全一致**，所以照抄即可。

同时产出 outline（章节骨架、开篇字段、文末默认人名），驱动新文章的结构校验。

**普通号走这条**（按 CSS 统计泛化，兜底方案）：

```bash
python scripts/learn_style.py --url u1 --url u2 --url u3 \
  --out references/style_profile.json --markdown references/style_profile.md
```

## Step 0.5 · 选对骨架

`references/outline-shoe-review.md` 里有两套骨架，**跑鞋篇和篮球鞋篇不一样，别混用**：

- 跑鞋篇 03 = 中底性能：脚感与体验 → 核心技术 / 脚感描述 / 不同场景表现（慢跑、节奏跑、长距离）
- 篮球鞋篇 03 = 中底性能：脚感与反馈 → 中底配置 / 脚感描述 / 实战表现
- 02、04 的子标题也不同

跑鞋关心透气、落差、推进效率、寿命公里数；球鞋关心支撑、抗扭、包裹锁定、场地适配。

## Step 1 · 选题（只写没写过的 + 最近比较火的）

用户定的规则：每次从**没写过的**鞋款里，挑**最近比较火的**跑鞋或篮球鞋，选一双。

```bash
# 先自动同步已发清单（公开合集页，不需要后台登录）
python scripts/fetch_published.py \
  --from-article https://mp.weixin.qq.com/s/BiqhYASeI583lBnamO_wZA \
  --from-article https://mp.weixin.qq.com/s/m29QBZ5gVfx6wzBwxPkbHg --write
python scripts/topic_pick.py list                    # 看已写台账
node ~/.kiro/skills/istarshine-trending-search/scripts/cli.js --task "最近7天跑鞋/篮球鞋热榜热搜"
node ~/.kiro/skills/istarshine-domestic-web-wide-search/scripts/cli.js stats \
  --q "跑鞋 测评 dateRestrict:d30" --metrics hotWords,trend
python scripts/topic_pick.py filter --candidates "候选1,候选2,候选3"
```

istarshine 搜索服务返回 503 时退回 `web_search`，别卡在这一步。

拿到 `fresh` 列表后按热度排序，给用户 3–5 个候选，每个说明：为什么现在热（带来源）、测评数据是否
够（国内外能找到几家实测）、素材盘有没有图。`fetch_published.py` 已能自动确认发布状态，不要再拿"发过没"去问用户。

注意栏目名不统一：篮球鞋用过「球鞋篇」（利刃5V2）和「篮球鞋篇」（韦德10）两种，写球鞋前先问用户用哪个。

发完草稿后追加台账：

```bash
python scripts/topic_pick.py add --name "<鞋名>" --column 跑鞋篇 --date 2026-08-30 --url <草稿或发布链接>
python scripts/topic_pick.py confirm --name "Adizero Adios Pro 4" --written no   # 用户说没发过就移除
```

## Step 2 · 测评数据搜集

国内：

```bash
node ~/.kiro/skills/istarshine-domestic-web-wide-search/scripts/cli.js search \
  --cx posts --q "<鞋名> 测评 实测 dateRestrict:d180" --num 100 --sort ctime:desc
```

海外（`web_search` + `web_fetch`）：RunRepeat（实验室数据最全）、Believe in the Run、
Doctors of Running、Road Trail Run、品牌官网规格页。

**每个数值当场落 claims.json**：`subject / metric / value / sources[{url,title,quote,date}]`，
`quote` 必须是原文里含这个数字的一句话。海外单位换算成公制后写 `value`，`quote` 留原文。
重量口径默认男款 US9 单只，口径不同必须标注。

## Step 3 · 得物二级市场价格（截图识价，用户不用手打）

开篇字段的 `二级平台价格：¥低～¥高` 就是这个。

**为什么不抓网页**（已实测，不要再试）：`dewu.com` 桌面站 JS 跑完后可见文本仅 997 字，全是导航
和"下载得物App"，无任何商品；页面调的商品接口 `app.dewu.com/api/v1/h5/commodity-pick-interfaces/pc/...`
返回 **485**（签名/风控拒绝）；`m.dewu.com` 返回 502。登录改变不了这些——得物没在网页端开放商品
数据。绕签名打 App 接口属于绕风控，不做。

**主路径**：让用户在得物 App 里把配色/价格列表截图（AirDrop 或存到 Mac），然后本机离线 OCR：

```bash
python scripts/dewu_ocr.py --dir ~/Desktop/dewu截图 --shoe "<鞋名>" \
  --out tmp/dewu_clean.json --dump tmp/ocr.json
```

用 macOS 自带 Vision 识别（`scripts/ocr_text.swift`），不联网、不需要 key、不碰账号。脚本把每个
`¥价格` 与最近的配色名配对，再跑剔除规则，输出 `stats.mainstream_range`。

**必须把识别出的配色和价格念给用户核对一遍**再进文章；`orphans` 里是找不到配色名的孤立价格，
`pages[].prices_found` 是每张图识出的价格数，都要一并汇报。

**兜底**：用户直接报文字也支持

```bash
python scripts/dewu_prices.py filter --shoe "<鞋名>" --out tmp/dewu_clean.json --text "黑白 829
全黑 845"
```

剔除规则见 `references/dewu-pricing.md`。价格 claim 的 `metric` 要带"得物"字样、`date` 填截图当天。

## Step 4 · 配图（从素材盘取，不用 AI）

素材盘：`<素材盘>/<你的文件夹>/<鞋款名>/`，每款有 封面 / 正视图 / 侧视图 / 后视图 / 俯视图 / 鞋面 / 鞋底 / 中底图片 / 拆解图 等实拍，外加封面 PSD。

每篇只需要 **4 张实拍**（01–04 每节开头一张）；子标题前的装饰条由渲染器自动插入，用账号既有素材，不需要准备也不需要上传。

```bash
python scripts/collect_assets.py list                      # 看有哪些鞋款、各有几张图
python scripts/collect_assets.py plan --shoe "<鞋款名>" \
  --out tmp/assets.json --copy-to imgs/                    # 挑图并按 章节_视角 命名复制到工作目录
```

同名多格式时自动优先 png/jpg（webp/avif 在公众号正文支持不稳，脚本会告警）。素材盘没挂载时返回 `not_found`。

素材盘缺图时才考虑：品牌官网产品图（文末注明来源）→ AI 生成（`gen_image.py`，必须标注"AI 生成示意图"，但本号历史没有图注，会破格式，最后手段）。

```bash
python scripts/gen_image.py --provider auto --prompt "..." --out imgs/x.png --fallback-card
```

**红线**：AI 图不得带真实品牌 logo、不得当作实拍。

## Step 5 · 写稿

写 `article.json`，模板模式 schema 见 `examples/article.rdfz.example.json`，骨架照
`references/outline-shoe-review.md`，文末署名照 `references/footer_defaults.json`
（测评人/编辑均为{测评人}，`reviewers` 留空 → 不输出「审核」行）。块类型：`img` `sub` `p` `fields` `lines` `scores`。`img` 只放 4 张实拍，装饰条不用写。
评分维度跑鞋 5 项写 `X/10`、球鞋 7 项写 `X 分`，别搞混。

行内标记只有两个，对应本号的语义化用色：

- `**文字**` → 蓝 `rgb(95,156,239)`，标正面结论
- `~~文字~~` → 橙 `rgb(249,110,87)`，标短板

一段强调 2–4 个短语，只强调结论性短句。目标约 2000 字。

**本号没有的东西，别加**：表格、引用块、分割线、图注、点赞在看引导语。

## Step 6 · 事实核查（硬闸门）

```bash
python scripts/fact_check.py --article article.json --claims claims.json \
  --report tmp/factcheck.json --min-sources 2 --allow-unsourced 2026
```

`blocking` 不为 0 不许进下一步，也不许调低 `--min-sources` 绕过。会拦：未登记的带单位数字
（含 `¥999` 这类前置货币写法）、数值类结论独立来源不足 2 个、引文里没有这个数字、同一指标
冲突、重量/堆高/落差/价格超出物理区间、价格类缺采集日期。评分 `8/10`、鞋码 `44.5 码`、
日期已自动豁免。细则见 `references/fact-check.md`。

## Step 7 · 渲染 + 上传图片 + 存草稿

```bash
python scripts/render_template.py --article article.json \
  --template references/template_rdfz.json \
  --outline references/outline_running.json --out article.html --strict

python scripts/mp_draft.py upload --image imgs/p1.png --out tmp/uploaded.json
# 把返回的 mmbiz.qpic.cn 地址回填 article.json 的 img.url，然后重新渲染
python scripts/render_template.py --article article.json \
  --template references/template_rdfz.json \
  --outline references/outline_running.json --out article.html --strict

python scripts/mp_draft.py draft --title "跑鞋篇——<鞋名>" --author "<作者>" \
  --digest "<摘要>" --html article.html
```

渲染器会校验章节号、章节名、子标题、开篇字段、每节实拍图数量是否与历史骨架逐项一致，不一致就告警；
子标题前的装饰条自动插入，已验证渲染出的图片序列与历史文章逐位相同。

公众号正文只显示素材库里的图，所以顺序是：渲染自查 → 上传拿地址 → 回填 → 重渲 → 灌编辑器。
`mp_draft.py` 只填内容、只存草稿，**永不点发表/群发/定时**，最后把浏览器留在编辑器页等你确认。
封面图、原创声明、话题标签仍需手动。

## 交付话术

**只存草稿，绝不发布。** 用户要自己检查排版对不对，所以每次做完只交付草稿，并明确告诉他去后台
哪里看、需要他核对什么（排版是否与历史一致、价格是否准确、封面要不要换）。


草稿位置和标题 + 选题理由 + 核查结论（claim 数 / 来源数 / blocking 0）+ 被省略的配色及原因 +
图片来源与是否 AI 生成 + 还需手动做的事。任何降级（用了默认排版、价格手工录入、图片没传成功、
实拍图不足 4 张）都要明说。

## 硬规则

1. 数字不过 `fact_check.py` 不出稿，一条都不例外。
2. 找不到第二个独立来源的数值宁可不写，不用"约""据说"蒙。
3. 得物只写主流配色区间，联名/限定直接省略、不提、不暗示，不做转售收益暗示。
4. AI 图必须标注，不伪造实拍、不伪造 logo。
5. 跑鞋和球鞋骨架不混用。
6. 不写"最强/第一/必买/稳赚"这类绝对化表述。
7. 不代替用户点发布，草稿是终点。
8. 不绕过任何平台的登录/验证码/风控。
