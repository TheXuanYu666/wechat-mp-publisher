# 公众号测评图文生产器 / WeChat Official Account Review Article Generator

[中文](#中文) | [English](#english)

---

## 中文

给鞋类测评公众号用的本地工具：**从选题到草稿全自动**，排版 1:1 复刻你自己历史文章的版式，正文里每个带单位的数字都必须能追到来源原文。

macOS 原生 App（Swift + WKWebView 外壳 + Python 后端），五步向导：

```
① 选鞋（自动搜热门、剔除写过的）
  - 国外跑鞋：RunRepeat 人气榜
  - 国产跑鞋：国内全网热度搜索
② 价格区间 + 发布日期
③ 拖四张图
④ 生成封面
⑤ 生成文章 → 保存到公众号草稿
```

### 为什么排版能对得上

不靠"字号 16px、行高 1.8"这种规则去逼近，而是**把你历史文章里的组件整段抠下来做占位符替换**。

秀米/135 这类模板排出来的文章，一个"图标 + 小标题"其实是嵌套七八层的 `<section>`，按标签去归类必然拆错。`extract_template.py` 从一篇已发文章里提取 11 个组件（外层容器、标题区、圆圈编号、正文卡片、图标子标题、段落、图片、正负强调、文末），全部是原文片段。实测这些组件在多篇文章间逐字一致，所以照抄就能对上。

### 数字必须可核验

`fact_check.py` 做机械核查，拦下这些情况：

- 正文出现带单位数字（g/mm/元/%/双/天…）但没在 `claims.json` 登记
- 数值类结论独立来源域名少于 2 个
- 来源引文里根本不含这个数字
- 同一指标前后冲突
- 重量/堆高/落差/价格超出物理合理区间
- 价格类结论缺采集日期

日期、评分（`8/10`、`8.5 分`）、鞋码会自动豁免。全球只有一家实验室的数据可以声明 `sole_source_ok` 并写明理由——例外是显式且留痕的，不是偷偷放宽标准。

### 文风也机械检查

`style_lint.py` 把口语化的写作要求变成 14 条可执行规则：禁用实验室缩写（SA/BR/AC/Nm）、禁止 `v41` 这种写法、型号名必须带品牌、不写产品改进建议、不引导读者买别的鞋、不做同价位横向比较、不提外部机构或网站、不用「」、蓝色只标优点橙色只标缺点、优缺点两段不标色、开篇字段顺序固定、跑鞋 5 项评分写 `X/10` 而球鞋 7 项写 `X 分`、图片位必须 4 个、章节骨架逐项比对。

中文情感词有歧义，这套判断做过针对性处理：`没有打滑`、`不累脚` 这类否定式不算负面；`落差` 里的"差"、`内翻` 里的"翻"不算情感词；`表现一般` 算负面但 `比一般跑鞋` 不算。

### 目录

```
app/            原生 App（Shell.swift 外壳 + server.py 后端 + index.html 界面）
scripts/
  hot_shoes.py         热门鞋款搜索（国外/国产双榜）
  fetch_published.py   同步公众号已发表台账
  extract_template.py  从历史文章抠排版组件
  render_template.py   组件模板渲染
  make_cover.py        封面生成（中英混排字体）
  fact_check.py        数字核查
  style_lint.py        文风检查
  mp_draft.py          公众号草稿自动化
  write_article.py     调用 Kiro CLI 自动写稿
references/
  outline_running.json     跑鞋篇骨架
  outline_basketball.json  篮球鞋篇骨架
  template_rdfz.json       排版组件模板（需从历史文章提取）
  published.json           已发表台账（运行时自动同步）
  candidates_*.json        热门候选缓存（运行时生成）
```

### 许可

本项目采用 MIT 许可证。配置、模板、台账等账号专属数据请只保留在本机，不要上传到公开仓库。

---

## English

A local tool for sneaker review WeChat Official Accounts: **end-to-end automation from topic selection to draft**, with 1:1 layout cloning from your historical articles, and every number with units must be traceable to source citations.

Native macOS App (Swift + WKWebView shell + Python backend), five-step wizard:

```
① Select Shoe (auto-search trending, exclude published)
  - Overseas: RunRepeat popularity ranking
  - Domestic: China-wide trending search
② Price Range + Release Date
③ Drag 4 Images
④ Generate Cover
⑤ Generate Article → Save to WeChat Draft
```

### Why Layout Matching Works

Instead of approximating with rules like "font-size: 16px, line-height: 1.8", we **extract entire component blocks from your historical articles and use them as templates**.

Articles formatted by Xiumi/135 have "icon + subtitle" structures nested 7-8 layers deep in `<section>` tags—categorizing by tag names will inevitably fail. `extract_template.py` extracts 11 components from a published article (outer container, title area, circle numbers, content cards, icon subtitles, paragraphs, images, positive/negative emphasis, footer)—all verbatim snippets. Tests show these components are byte-identical across multiple articles, so copying them ensures perfect matching.

### Numbers Must Be Verifiable

`fact_check.py` performs mechanical verification, blocking these cases:

- Numbers with units (g/mm/yuan/%/pairs/days…) appearing in text but not registered in `claims.json`
- Numeric claims sourced from fewer than 2 independent domains
- Source citations not containing the claimed number
- Contradictions in the same metric across text
- Weight/stack height/drop/price exceeding physically reasonable ranges
- Price claims missing collection date

Dates, ratings (`8/10`, `8.5 points`), and shoe sizes are auto-exempted. Data from globally unique labs can declare `sole_source_ok` with justification—exceptions are explicit and traceable, not silent standard-lowering.

### Style Also Mechanically Checked

`style_lint.py` converts colloquial writing requirements into 14 executable rules: ban lab abbreviations (SA/BR/AC/Nm), forbid `v41` notation, require brand names with model numbers, no product improvement suggestions, no guiding readers to other shoes, no same-price-range comparisons, no external institutions/websites, no「」, blue for pros only orange for cons only, no colors in pros/cons list sections, fixed opening field order, running shoe ratings as `X/10` vs basketball `X points`, exactly 4 image slots, section skeleton item-by-item matching.

Chinese sentiment words are ambiguous, handled specifically: `没有打滑` (no slipping), `不累脚` (not tiring) as negations aren't negative; `落差` (drop) contains "差" but isn't sentiment; `内翻` (pronation) contains "翻" but isn't sentiment; `表现一般` (mediocre) is negative but `比一般跑鞋` (better than average shoes) isn't.

### Directory Structure

```
app/            Native App (Shell.swift + server.py + index.html)
scripts/
  hot_shoes.py         Trending shoes search (overseas/domestic dual sources)
  fetch_published.py   Sync published articles ledger
  extract_template.py  Extract layout components from historical articles
  render_template.py   Component template rendering
  make_cover.py        Cover generation (mixed CJK/Latin fonts)
  fact_check.py        Numeric verification
  style_lint.py        Style checking
  mp_draft.py          WeChat draft automation
  write_article.py     Auto-writing via Kiro CLI
references/
  outline_running.json     Running shoe article skeleton
  outline_basketball.json  Basketball shoe article skeleton
  template_rdfz.json       Layout component templates (extract from history)
  published.json           Published articles ledger (auto-synced)
  candidates_*.json        Trending candidates cache (runtime)
```

### License

This project is licensed under MIT. Account-specific data (config, templates, ledgers) should remain local only—do not upload to public repositories.
