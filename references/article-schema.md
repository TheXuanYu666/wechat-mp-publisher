# article.json 结构

```json
{
  "title": "标题（公众号限 64 字）",
  "author": "作者名",
  "digest": "摘要，120 字内",
  "unsourced_ok": ["2026", "18"],
  "blocks": [
    { "type": "p", "text": "开头段。**加粗**会用主色强调。" },
    { "type": "h2", "text": "一、这双鞋凭什么被讨论" },
    { "type": "h3", "text": "中底" },
    { "type": "quote", "text": "一句话结论放这里" },
    { "type": "list", "items": ["要点一", "要点二"] },
    { "type": "olist", "items": ["第一步", "第二步"] },
    { "type": "img", "url": "https://mmbiz.qpic.cn/...", "alt": "侧面图", "caption": "图：品牌官网产品图" },
    { "type": "table",
      "headers": ["项目", "参数", "来源"],
      "rows": [["重量", "291g", "RunRepeat 实测"]],
      "caption": "规格参数，单位已统一为公制" },
    { "type": "hr" },
    { "type": "sources", "title": "数据来源",
      "items": [{ "title": "RunRepeat 评测", "url": "https://...", "date": "2026-05-12" }] },
    { "type": "raw", "html": "<p>极少数需要手写 HTML 的情况</p>" }
  ]
}
```

字段说明：

| 字段 | 作用 |
|---|---|
| `unsourced_ok` | 白名单数字，年份、款号这类不需要来源的数值写这里，否则 `fact_check.py` 会报 unsourced |
| `img.url` | 必须是 `https://mmbiz.qpic.cn/...`（素材库地址）。本地路径渲染时会告警，`mp_draft.py draft` 会直接拒绝 |
| `img.caption` | AI 生成图必须含"AI 生成示意图" |
| `table.rows` | 单元格文本同样受事实核查约束，数字要在 claims 里登记 |
| `sources.items` | 与 claims.json 的来源保持一致，缺失时渲染会告警 |

`**文字**` 是唯一支持的行内标记，渲染成主色加粗。不要在 `text` 里写 HTML 标签（会被转义），需要 HTML 请用 `raw` 块。

# claims.json 结构

```json
{
  "claims": [
    {
      "id": "c1",
      "subject": "Nike Vomero 18",
      "metric": "重量",
      "value": "291g",
      "sources": [
        { "title": "RunRepeat lab test", "url": "https://runrepeat.com/...",
          "quote": "Weight: 291g (10.3 oz) in men's US 9", "date": "2026-05-12" },
        { "title": "Nike 官网规格", "url": "https://www.nike.com/...",
          "quote": "重量：291 克", "date": "2026-05-20" }
      ]
    },
    {
      "id": "c2",
      "subject": "Nike Vomero 18",
      "metric": "得物二级市场价（黑白配色）",
      "value": "829元",
      "sources": [
        { "title": "得物商品页", "url": "https://www.dewu.com/spu/...",
          "quote": "¥829 起", "date": "2026-08-30" }
      ]
    }
  ]
}
```

要求：

- `value` 里的数字必须能在至少一条 `quote` 里找到，否则报 `quote_mismatch`
- 数值类 claim 需要 ≥2 个**不同注册域名**的来源（`--min-sources` 可调，不建议降到 1）
- 同一 `subject + metric` 只能有一个 `value`，冲突会 blocking
- `metric` 含"二级"或"得物"时，来源域名必须是得物系，否则 warning
- 海外单位换算后写 `value`，`quote` 保留原文（原文里的 `10.3 oz` 不影响匹配，因为 `291` 也在引文里）
