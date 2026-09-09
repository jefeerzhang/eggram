# 设计：rule 公式页结构化排版 + 分步动效（两期）

> 状态：已与用户对齐（方案 2；范围仅 `rule` + `layout_variant: formula`；先排版后动效）  
> 日期：2026-09-09  
> 相关：`docs/formulas.md`、`docs/json-schema.md`、`docs/motion.md`、`templates/layout-rule-formula.html`  
> 明确不做：#27 hyperframes 整页换皮、KaTeX、默认改 1080p

## 背景与目标

长公式目前挤在扁平 `body` + 居中卡片里，字号一刀切、拆解槽位误用 `zh`/badge。动效只有整页 CSS 推拉，无法按公式结构分段出场。

**目标（两期）：**

1. **第一期（排版）**：为 `rule` + `formula` 变体引入结构化 `formula` 对象，主式可读、分项清晰；旧分镜兼容。  
2. **第二期（动效）**：在同一数据上按 `parts[].id` 做轻量拟物/分步高亮，不引入整页 timeline。

**成功标准：** 金融/理科课里的「整式 + 分子分母说明」一眼可读；旧课不炸；preview 闸门仍能拦住溢出。

## 方案选择

| 方案 | 结论 |
| --- | --- |
| 1. 仅 `parts[]` + 仍用扁平 `body` | 否：分式排版不够 |
| 2. `formula` 对象（display / num / den / parts） | **采用** |
| 3. KaTeX / MathML | 否：与 escape/闸门/轻动效冲突大 |

---

## §1 字段与兼容

### 启用条件

`kind: "rule"` 且 `layout_variant: "formula"` 且存在对象字段 `formula`。

### `formula` 对象

| 字段 | 必填 | 说明 |
| --- | --- | --- |
| `display` | 条件\* | 单行整式（可 `<sub>`/`<sup>`/`**`） |
| `num` | 否 | 分子文本 |
| `den` | 否 | 分母文本 |
| `parts` | 推荐 | 分项数组 |

\* `num` 与 `den` 都有则可省略 `display`（画面以分式为主）；否则 `display` 必填。两者都有时以分式为主，`display` 可作对照。

### `parts[]`

| 字段 | 必填 | 说明 |
| --- | --- | --- |
| `id` | ✅ | 页内唯一，如 `num` / `den` / `p1`（二期动效用） |
| `label` | ✅ | 短标签 |
| `text` | ✅ | 说明；可 `<sub>`/`**` |

长度：2–4。

### 与旧字段

| 字段 | 语义 |
| --- | --- |
| `body` | 有 `formula` 时可空；若非空 → **warn**「以 formula 为准，body 忽略」 |
| `header` / `sub` / `narrate` | 不变 |
| `zh` | formula 变体下不再充当步骤；步骤只来自 `parts` |
| 无 `formula` | 与现网完全一致（仍要求 `body`） |

### 示例

```json
{
  "kind": "rule",
  "layout_variant": "formula",
  "header": "夏普比率",
  "sub": "风险调整后收益",
  "formula": {
    "num": "R<sub>p</sub> − R<sub>f</sub>",
    "den": "σ<sub>p</sub>",
    "parts": [
      {"id": "num", "label": "分子", "text": "超额收益（组合收益 − 无风险利率）"},
      {"id": "den", "label": "分母", "text": "组合收益的波动 σ<sub>p</sub>"}
    ]
  },
  "narrate": "夏普比率等于超额收益除以总风险。"
}
```

---

## §2 Layout（`layout-rule-formula.html`）

### 层级

1. 标题区：`header` + badge + 线 + `sub`  
2. 主公式区：有 `num`+`den` → 分式块（分子 / accent 分数线 / 分母）；否则 `display` 卡片  
3. 分项区：`parts` 横排（2）或网格（3–4）；每项 label + text  

### 长公式

- 主区 max-width ≈ 960px；分子分母可各自换行  
- 分项字号约 body×0.55–0.65  
- preview 选择器覆盖 `.formula-frac` / `.part-text` 等  

### 接缝

- gate 预渲染 `__FORMULA_MAIN__`、`__PARTS__`（或等价槽）注入 layout  
- 文本走 `_escape` / `highlight_body`  
- 第一期一次性出场；主式/part 带稳定 class / `data-part-id` 供二期绑定  

### 不做

KaTeX、其它 kind、改默认分辨率。

---

## §3 闸门与第一期验收

### 闸门

存在 `formula` 时：

- 必须为 object  
- `num`+`den` 齐全 **或** `display` 非空  
- `parts` 若有：长度 2–4；字段齐全；`id` 唯一  
- `body` 非空 → warn  
- 其它 kind 上出现 `formula` → warn（可选，推荐）

无 `formula`：旧规则不变。

### 文档

- 更新 `json-schema.md`、`formulas.md`；SKILL pointer 可指向新节  

### Done when（第一期）

1. 用 `num`/`den`/`parts` 的示例课渲出分式 + 分项  
2. 仅 `body` 的旧 formula 课回归通过  
3. 非法 `formula` 闸门失败  
4. `--preview` 主式/分项无明显溢出  
5. 不改 worker 协议、默认分辨率、其它 layout  

---

## §4 第二期动效（纲要）

### 原则

CSS 变量 + 秒语义；用 `parts[].id`；不上 #27 / CDN / WebGL。

### 建议时间线

| 阶段 | 画面 |
| --- | --- |
| 段首 | 标题静入；公式卡轻抬起 |
| 讲整式 | 主式 `focus` |
| 逐项 | 对应 part `pulse`/高亮，其它略降透明 |
| hold | 冻末态 |

### 拟物（轻）

卡入场位移+阴影；label 点亮；可选分数线宽度 0→100%。节奏用现有 `motion` 数组 `delay`，或默认按 parts 均分。

### 衔接

第一期只保证 DOM 钩子；第二期不加新 JSON 形状。

---

## 实现触点（供后续 plan）

| 区域 | 文件（预期） |
| --- | --- |
| Schema / 文档 | `docs/json-schema.md`、`docs/formulas.md`、`SKILL.md` |
| 闸门与槽位 | `scripts/storyboard_gate.py` |
| Layout | `templates/layout-rule-formula.html` |
| 测试 | `tests/test_make_video.py`（escape/闸门/渲染 HTML 断言） |
| 二期 | `docs/motion.md` + gate/CSS 变量扩展 |

## 非目标

- 关闭的 #27（NOT_PLANNED）不复活  
- 自动 ASR 对齐旁白与 part  
- 全局改 720→1080  

## 开放问题

无（四段设计均已口头确认）。迁移现有 gitignored 课（如夏普）在实现 plan 里列为手工验证项即可。
