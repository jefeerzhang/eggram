<!-- markdownlint-disable MD033 -->
# 公式渲染

教学微课里常见数学/金融公式：分子分母、上下标、希腊字母、特殊符号。
Storyboard JSON 的 `body` / `sub` / `header` 字段怎么写这些。

## 渲染管线

`scripts/storyboard_gate.py` 的 `_escape()` 是教学文本到 HTML 的唯一入口。
流程：先按白名单提取标签为占位符（避免被 escape 干掉）→ escape 其它特殊字符
→ 还原占位符为 HTML。

## 白名单标签（透传）

| 标签 | 用途 | 例子 | 渲染 |
| --- | --- | --- | --- |
| `<br>` / `<br/>` / `<br />` | 换行 | `"A<br>B"` | A<br>B |
| `<sub>...</sub>` | 下标 | `"R<sub>p</sub>"` | R<sub>p</sub> |
| `<sup>...</sup>` | 上标 | `"X<sup>2</sup>"` | X<sup>2</sup> |

**白名单外**的 `<...>` 仍被 escape 为 `&lt;...&gt;` 按字面显示。
这是 XSS 防护——分镜 JSON 是用户自管内容，但不能注入任意 HTML。

## 结构化 formula（推荐）

`kind: "rule"` 且 `layout_variant: "formula"` 时，用顶层 `formula` 对象描述主式与分项拆解（分式排版 + `parts` 槽位），替代把整式塞进扁平 `body`。

| 字段 | 必填 | 说明 |
| --- | --- | --- |
| `display` | 条件\* | 单行整式（可 `<sub>`/`<sup>`/`**`） |
| `num` | 否 | 分子文本 |
| `den` | 否 | 分母文本 |
| `parts` | 推荐 | 分项数组，长度 2–4；每项须 `id` / `label` / `text`（`id` 页内唯一） |

\* `num` 与 `den` 都有则可省略 `display`（画面以分式为主）；否则 `display` 非空。

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

**兼容：** 无 `formula` 时行为与现网一致——仍要求非空 `body`，主式来自 `body`，分项走旧 `zh`/badge 双步。  
**并存警告：** 同时提供 `formula` 与非空 `body` 时，*闸门* 发出 warning「以 formula 为准，body 忽略」，画面只读 `formula`。  
**顺带：** `parts` 不只是排版槽位——它同时决定公式页的逐项点亮顺序，见 [motion.md](motion.md#公式页分步动效)。

## 避坑

### ❌ 直接写 `R_p` 不行

`_escape` 末尾有 `.replace("_", "&#95;")`，把下划线转成实体，
目的是中和 `__...__` 槽位 token（避免内容里的 `__FOO__` 被渲染管线误判为残留占位符）。
副作用：用户写的 `R_p` 也会被转成 `R&#95;p`，视觉上变成 `R_p`（带下划线连字符，非下标）。

**正确**：用 `<sub>` 标签。

### ❌ 占位符不能带下划线，也不能用正文里可能出现的 `@...@`

`_escape` 内部用 **NUL 包裹**的短 token（并先剥掉原文里的 NUL），避免旧版 `@BR@`
被正文原样撞上后误还原成 `<br>`。

如果你将来扩展占位符：**禁用下划线**（会被 `.replace("_")` 误伤），也**不要**用
用户可能敲出的明文 token。参考 `scripts/storyboard_gate.py` 的 `_escape()`。

### ❌ 不可用 `<script>` 等任意标签

白名单外标签一律 escape。`<script>alert(1)</script>` 会显示成文本，不会执行。

### ❌ 不要嵌套 `<sub>` / `<sup>`

非贪婪匹配只吃最内层一对；嵌套会产出畸形 HTML。公式里写一层即可。

## 例子

```json
{
  "kind": "rule",
  "header": "夏普比率",
  "sub": "(R<sub>p</sub> − R<sub>f</sub>) / σ<sub>p</sub>",
  "body": "**分子 = 超额收益（R<sub>p</sub> − R<sub>f</sub>）**<br>**分母 = 总风险（σ<sub>p</sub>）**"
}
```

渲染结果：`R_p`、`σ_p` 以下标形式显示，`σ` 用希腊字母，`**` 部分按对应 style token
高亮（rule 用 accent 色）。

## 什么时候需要扩展

如果白名单不够用（例如需要分式 `\frac`、根号 `\sqrt`、求和 `\sum`），两条路：

1. **加白名单标签**（最小改）：在 `_escape` 仿照 `<sub>` 处理 `<span class="frac">` 等，
   在 `templates/layout-*.html` 加 CSS 排版。
2. **引入 KaTeX**（重量级）：违背 motion.md 的 CSS 轻动效原则，谨慎。

当前选择：白名单 `<sub>`/`<sup>` 覆盖 90% 金融/理公式需求。

## 相关文件

- [`scripts/storyboard_gate.py`](../scripts/storyboard_gate.py) — `_escape()` 实现
- [`docs/json-schema.md`](json-schema.md) — body / sub / header 字段定义
- [`docs/motion.md`](motion.md) — 动画与样式 token
