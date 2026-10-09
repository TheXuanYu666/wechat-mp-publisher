---
name: wechat-mp-publisher
description: 'End-to-end WeChat Official Account article production: topic selection → domestic+overseas review data aggregation → Dewu secondary market pricing → fact-checking → 1:1 HTML layout cloning from historical articles → image insertion → draft saving to WeChat backend. Layout relies on extract_template.py to extract component blocks from historical articles for placeholder substitution, not manual CSS rules; every number with units must be registered in claims.json and pass fact_check.py verification. Use when users need to write/publish WeChat articles, especially sneaker/basketball shoe reviews with pricing content. / 端到端生产公众号图文：选题 → 全网测评数据搜集（国内+海外）→ 得物二级市场配色价格 → 事实核查 → 按本号历史排版 1:1 复刻 HTML → 配图 → 灌入公众号后台存草稿。排版靠 extract_template.py 把历史文章的组件整段抠出来做占位符替换，不靠人工描述、不靠 CSS 泛化；正文里每个带单位的数字都必须在 claims.json 登记并通过 fact_check.py。当用户要写/发公众号文章，尤其是跑鞋/球鞋测评+价格类内容时使用。'
metadata:
  author: your-name
  display_name: 公众号图文生产 / WeChat Article Generator
  version: 2.1.0
  tags:
    - 公众号
    - WeChat
    - 内容生产
    - Content Production
    - 事实核查
    - Fact-Checking
  requires:
    bins:
      - python3
      - node
    optional_env:
      - OPENAI_API_KEY
      - DASHSCOPE_API_KEY
      - ISTARSHINE_API_KEY
---

# 公众号图文生产 / WeChat Official Account Article Generator

[中文](#中文) | [English](#english)

---

## 中文

从"今天发什么"到"后台里躺着一篇可预览的草稿"。核心两件事：**排版原样复刻历史文章**，**数字必须可核验**。

当前已适配账号：**<你的公众号>**（秀米/135 模板号，栏目：跑鞋篇 / 篮球鞋篇）。

### 环境准备（首次一次）

```bash
cd ~/.kiro/skills/wechat-mp-publisher
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
```

后续 `python` 均指 `~/.kiro/skills/wechat-mp-publisher/.venv/bin/python`，命令都在 skill 目录下执行。

### 使用方式

#### 方式一：原生 App（推荐）

```bash
open /Applications/步界社公众号生成器.app
```

五步向导：选鞋（国外/国产双榜）→ 价格日期 → 四张图 → 封面 → 生成文章并保存草稿。

#### 方式二：命令行

```bash
# 热门鞋款搜索（国外 RunRepeat 榜单）
python scripts/hot_shoes.py --market overseas --out references/candidates_overseas.json --limit 5

# 热门鞋款搜索（国产 istarshine 全网热度）
python scripts/hot_shoes.py --market domestic --out references/candidates_domestic.json --limit 5

# 自动写稿
python scripts/write_article.py --shoe "Nike Pegasus 42" --column 跑鞋篇

# 生成封面
python scripts/make_cover.py --shoe "李宁 赤兔9 PRO" --side-view 01_侧面.png --out 封面.png

# 渲染文章
python scripts/render_template.py --article article.json --template references/template_rdfz.json --outline references/outline_running.json --out article.html

# 保存到公众号草稿
python scripts/mp_draft.py draft --html article.html --title "跑鞋篇——Nike Pegasus 42" --author 步界社 --digest "测评Nike Pegasus 42" --save --cover 封面.png --album 跑鞋 --original --claim-source
```

### 核心特性

- **双榜选题**：国外 RunRepeat 人气榜 + 国产 istarshine 全网热度
- **公众号查重**：只排除后台"已发表"内容，本地稿件标记复用
- **1:1 排版复刻**：从历史文章提取组件模板，不靠 CSS 规则泛化
- **数字强制核查**：每个带单位数字必须在 claims.json 登记来源
- **封面字体混排**：国产鞋中文+数字用行楷、英文用 Herculanum；英文鞋全用 Herculanum
- **草稿自动化**：标题/作者/摘要/正文/合集/封面/原创/创作来源一键设置

### 许可

MIT License. 配置、模板、台账等账号专属数据请只保留在本机。

---

## English

From "what to publish today" to "a previewable draft in the backend". Two core principles: **verbatim layout cloning from historical articles**, **mandatory verifiable numbers**.

Currently adapted for: **<Your WeChat Account>** (Xiumi/135 template account, columns: Running Shoes / Basketball Shoes).

### Setup (One-time)

```bash
cd ~/.kiro/skills/wechat-mp-publisher
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
```

All `python` commands below refer to `~/.kiro/skills/wechat-mp-publisher/.venv/bin/python`, executed in the skill directory.

### Usage

#### Method 1: Native App (Recommended)

```bash
open /Applications/步界社公众号生成器.app
```

Five-step wizard: Select Shoe (Overseas/Domestic dual sources) → Price & Date → Four Images → Cover → Generate Article & Save Draft.

#### Method 2: Command Line

```bash
# Trending shoes search (Overseas RunRepeat ranking)
python scripts/hot_shoes.py --market overseas --out references/candidates_overseas.json --limit 5

# Trending shoes search (Domestic istarshine trending)
python scripts/hot_shoes.py --market domestic --out references/candidates_domestic.json --limit 5

# Auto-write article
python scripts/write_article.py --shoe "Nike Pegasus 42" --column 跑鞋篇

# Generate cover
python scripts/make_cover.py --shoe "Li-Ning Chitu 9 PRO" --side-view 01_side.png --out cover.png

# Render article
python scripts/render_template.py --article article.json --template references/template_rdfz.json --outline references/outline_running.json --out article.html

# Save to WeChat draft
python scripts/mp_draft.py draft --html article.html --title "Running Shoe Review — Nike Pegasus 42" --author YourAccount --digest "Nike Pegasus 42 Review" --save --cover cover.png --album running --original --claim-source
```

### Core Features

- **Dual-Source Topic Selection**: Overseas RunRepeat popularity + Domestic istarshine trending
- **WeChat Deduplication**: Only excludes backend "published" content, local drafts marked as reusable
- **1:1 Layout Cloning**: Extracts component templates from historical articles, no CSS rule generalization
- **Mandatory Numeric Verification**: Every number with units must be registered with source in claims.json
- **Mixed Font Cover**: Domestic shoes use Xingkai for Chinese+digits, Herculanum for English; Overseas shoes use Herculanum throughout
- **Draft Automation**: One-click setup for title/author/summary/content/album/cover/original/claim-source

### License

MIT License. Account-specific data (config, templates, ledgers) should remain local only.
