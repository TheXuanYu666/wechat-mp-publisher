# 公众号测评图文生产器

给鞋类测评公众号用的本地工具：**从选题到草稿全自动**，排版 1:1 复刻你自己历史文章的版式，正文里每个带单位的数字都必须能追到来源原文。

macOS 原生 App（Swift + WKWebView 外壳 + Python 后端），五步向导：

```
① 选鞋（自动搜热门、剔除写过的）
② 价格区间 + 发布日期
③ 拖四张图
④ 生成封面
⑤ 生成文章 → 保存到公众号草稿
```

## 为什么排版能对得上

不靠"字号 16px、行高 1.8"这种规则去逼近，而是**把你历史文章里的组件整段抠下来做占位符替换**。

秀米/135 这类模板排出来的文章，一个"图标 + 小标题"其实是嵌套七八层的 `<section>`，按标签去归类必然拆错。`extract_template.py` 从一篇已发文章里提取 11 个组件（外层容器、标题区、圆圈编号、正文卡片、图标子标题、段落、图片、正负强调、文末），全部是原文片段。实测这些组件在多篇文章间逐字一致，所以照抄就能对上。

## 数字必须可核验

`fact_check.py` 做机械核查，拦下这些情况：

- 正文出现带单位数字（g/mm/元/%/双/天…）但没在 `claims.json` 登记
- 数值类结论独立来源域名少于 2 个
- 来源引文里根本不含这个数字
- 同一指标前后冲突
- 重量/堆高/落差/价格超出物理合理区间
- 价格类结论缺采集日期

日期、评分（`8/10`、`8.5 分`）、鞋码会自动豁免。全球只有一家实验室的数据可以声明 `sole_source_ok` 并写明理由——例外是显式且留痕的，不是偷偷放宽标准。

## 文风也机械检查

`style_lint.py` 把口语化的写作要求变成 14 条可执行规则：禁用实验室缩写（SA/BR/AC/Nm）、禁止 `v41` 这种写法、型号名必须带品牌、不写产品改进建议、不引导读者买别的鞋、不做同价位横向比较、不提外部机构或网站、不用「」、蓝色只标优点橙色只标缺点、优缺点两段不标色、开篇字段顺序固定、跑鞋 5 项评分写 `X/10` 而球鞋 7 项写 `X 分`、图片位必须 4 个、章节骨架逐项比对。

中文情感词有歧义，这套判断做过针对性处理：`没有打滑`、`不累脚` 这类否定式不算负面；`落差` 里的"差"、`内翻` 里的"翻"不算情感词；`表现一般` 算负面但 `比一般跑鞋` 不算。

## 目录

```
app/            原生 App（Shell.swift 外壳 + server.py 后端 + index.html 界面）
scripts/
  extract_template.py  从历史文章抠排版组件
  learn_style.py       通用号的 CSS 风格统计（模板号用不上）
  render_template.py   组件模板渲染
  render_article.py    通用 CSS 渲染（兜底）
  fact_check.py        数字核查
  style_lint.py        文风检查
  write_article.py     调本机 kiro-cli 写稿
  hot_shoes.py         搜热门鞋（RunRepeat 榜）
  fetch_published.py   从公开合集页同步已发清单
  topic_pick.py        选题查重台账
  make_cover.py        生成封面（中英文分别用不同字体）
  collect_assets.py    素材盘图片清点
  mp_draft.py          公众号后台自动化（上传、封面、合集、原创、存草稿）
  dewu_ocr.py          得物截图 OCR 识价
  dewu_prices.py       价格清洗与离群剔除
  gen_image.py         配图生成兜底
references/     排版规范、核查规则、写作骨架
examples/       稿件与 claims 的结构示例
```

## 用起来

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
cp config.example.json config.json    # 改成自己公众号的信息

# 学一遍自己号的排版（给一篇已发文章的公开链接）
.venv/bin/python scripts/extract_template.py \
  --url https://mp.weixin.qq.com/s/xxxx \
  --out references/template.json --outline-out references/outline.json

# 起 App
.venv/bin/python app/server.py
```

打包成 `.app`：

```bash
swiftc -O -o app/build/Shell app/Shell.swift
# 再按 Info.plist 组包，图标用你自己的社标
```

## 依赖与前提

- macOS（封面字体、离线 OCR 都用系统能力）
- 已安装 Google Chrome（公众号后台自动化复用系统 Chrome）
- 写稿功能需要本机装有 [Kiro CLI](https://kiro.dev)，复用其订阅，不需要额外的模型 API key
- 首次需扫码登录公众号后台一次，登录态存在本机 `~/.kiro/mp-browser-profile`，不上传

## 几条硬规则

1. 数字过不了核查就不出稿，不许调低 `--min-sources` 绕过
2. 找不到第二个独立来源的数值宁可不写
3. 二级市场价只写主流区间，联名与限定直接省略，不做转售收益暗示
4. AI 生成图必须标注，不伪造实拍与品牌 logo
5. **只存草稿，不自动发表**——发表不可撤回，留给人点

## 不做什么

- 不绕过任何平台的登录、验证码、风控
- 不抓取得物网页（实测其桌面站无商品数据，价格靠 App 内 OCR 截图或手工录入）
- 不读取、不打印、不上传浏览器 Cookie

## License

MIT
