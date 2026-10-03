<!-- markdownlint-disable MD033 -->
# 公式渲染

教学微课里常见数学/金融公式：分子分母、上下标、希腊字母、特殊符号。
Storyboard JSON 的 `body` / `sub` / `header` 字段怎么写这些。

## 渲染管线

`scripts/storyboard_gate.py` 的 `_escape()` 是教学文本到 HTML 的唯一入口。
流程：先 escape 特殊字符（`&` `<` `>` `"` `'`），把下划线中和成实体，把换行转成
`<br>`；再把**转义形态**（`&lt;sub&gt;`）还原成真标签（`<sub>`）。
所以正文里手写的 `&lt;sub&gt;` 只会按字面显示，不会被还原成标签。

## 白名单标签（透传）

| 标签 | 用途 | 例子 | 渲染 |
| --- | --- | --- | --- |
| `<br>` / `<br/>` / `<br />` | 换行 | `"A<br>B"` | A<br>B |
| `<sub>...</sub>` | 下标 | `"R<sub>p</sub>"` | R<sub>p</sub> |
| `<sup>...</sup>` | 上标 | `"X<sup>2</sup>"` | X<sup>2</sup> |
| `<rad>...</rad>` | 根号（带上划线） | `"σ = <rad>(w<sup>T</sup>Σw)</rad>"` | σ = √，根号线一直压到 (w<sup>T</sup>Σw) 结束 |

`<rad>` 只把 U+221A 那个字符补上根号线，线由 `templates/layout-*.html` 的 `.rad`
边框画出：

```css
.rad{display:inline-block;position:relative;padding-left:.6em;border-top:2.5px solid currentColor}
.rad::before{content:"√";position:absolute;left:.02em;top:-.04em;font-size:1.05em;
             line-height:1;transform:scaleY(1.35);transform-origin:top left}
```

单独写 `√(...)` 时，U+221A 只是一个普通字符，没有上划线，屏幕上读成"√("
（像函数调用）而不是根式——这是 `<rad>` 存在的全部理由。`currentColor` 取的是
外层 `.hl` / `.err` 的颜色，所以根号跟着高亮走。

**白名单外**的 `<...>` 仍被 escape 为 `&lt;...&gt;` 按字面显示。
这是 XSS 防护——分镜 JSON 是用户自管内容，但不能注入任意 HTML。

## 结构化 formula（推荐）

`kind: "rule"` 且 `layout_variant: "formula"` 时，用顶层 `formula` 对象描述主式与分项拆解（分式排版 + `parts` 槽位），替代把整式塞进扁平 `body`。

| 字段 | 必填 | 说明 |
| --- | --- | --- |
| `display` | 条件\* | 单行整式（可 `<sub>`/`<sup>`/`<rad>`/`**`） |
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

### ❌ 没有再「先提取占位符」这一层

早期版本先把标签抽成占位符（`@BR@` 一类，还用 NUL 包裹）再还原，现在没有这层了：
`_escape` **先 escape，再按转义形态还原白名单标签**。两条后果：

- 正文里手写 `@BR@`、`&lt;sub&gt;` 都按字面显示，不可能被误还原成标签
  （`tests/test_make_video.py` 钉住了这条）；
- 加新标签只改 `_WHITELIST_TAGS` 一条「转义形态 → 真标签」规则 + 模板 CSS，
  不必再操心 escape 顺序。

### ❌ 不可用 `<script>` 等任意标签

白名单外标签一律 escape。`<script>alert(1)</script>` 会显示成文本，不会执行。

### ❌ 不要嵌套 `<sub>` / `<sup>` / `<rad>`

非贪婪匹配只吃最内层一对；嵌套会产出畸形 HTML。公式里写一层即可。
`<sup>` 写在 `<rad>` **里面**是允许的（`<rad>w<sup>T</sup>Σw</rad>`）——
它们不是同一种标签的嵌套。

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

如果白名单不够用（例如需要分式 `\frac`、求和 `\sum`、分段函数），两条路：

1. **加白名单标签**（最小改）：在 `_WHITELIST_TAGS` 加一条「转义形态 → 真标签」规则，
   在 `templates/layout-*.html` 加对应 CSS 排版。根号 `<rad>` 就是这么加的，照它抄：
   正则吃 `&lt;rad&gt;(.*?)&lt;/rad&gt;`，还原成 `<span class="rad">…</span>`，
   线由 CSS 边框画（不改 HTML 结构、不引外部依赖）。
2. **引入 KaTeX**（重量级）：违背 motion.md 的 CSS 轻动效原则，谨慎。

当前选择：白名单 `<sub>`/`<sup>`/`<rad>` 覆盖 90% 金融/理公式需求。

## 相关文件

- [`scripts/storyboard_gate.py`](../scripts/storyboard_gate.py) — `_escape()` 实现
- [`docs/json-schema.md`](json-schema.md) — body / sub / header 字段定义
- [`docs/motion.md`](motion.md) — 动画与样式 token
