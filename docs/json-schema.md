# 分镜 JSON

权威字段表。教学义务见 [`teaching-method.md`](teaching-method.md)；样例见 `examples/now_progressing.json`。

## 顶层

| 字段 | 必填 | 说明 |
| --- | --- | --- |
| title | ✅ | 知识点名 |
| voice | ✅ | 默认音色：mimo_default/冰糖/茉莉/苏打/白桦/Mia/Chloe/Milo/Dean |
| voices | | 对话模式角色映射（如 `{"narrator":"苏打","student":"冰糖"}`） |
| style | | `teaching` / `classroom` / `explainer`；CLI `--style` 可覆盖 |
| motion | | 顶层 bool，默认 true |
| fps | | 正整数，默认 30（0、负数、布尔、非整数 → *闸门* 拒绝） |
| width / height | | 默认 1920×1080（#27 起升级；显式传值优先） |
| blocks | | 顶层 bool，默认 true——title/rule/mistake 页整页换肤为 hyperframes 动画 block（[`templates/blocks/README.md`](../templates/blocks/README.md)）；`false` 整支走静态布局 |
| scenes | ✅ | 分镜数组 |

## scenes[]

| 字段 | 必填 | 说明 |
| --- | --- | --- |
| kind | ✅* | title / rule / diagram / example / mistake / practice / answer / summary |
| role | | *page-role*；可代替 kind；与 kind 同写须一致 |
| voice | | 每页音色覆盖：角色 ID（如 `"narrator"`）或音色名（如 `"苏打"`），省略用顶层默认 |
| layout_variant | | 排版变体 ID（如 `"side"` / `"formula"`），回退默认 layout |
| motion | | 字符串或 effects 数组，见 [`motion.md`](motion.md) |
| header | ✅ | 「学习者此刻做什么」 |
| sub | 推荐 | 副题；mistake=诱因；example 可兼中文义 |
| body | ✅ | 主体；`**...**` = 高亮知识点；**换行用 `<br>`，严禁 `\n`** |
| wrong_body | example side | 错误示例；`kind: "example"` 且 `layout_variant: "side"` 时须为非空字符串，`**...**` 标红 |
| narrate | ✅ | TTS 口语短句 |
| chart | diagram | 图表对象（`preset` + 数据），见下方说明 |
| hold | practice | ≥3.0（样例 3.0） |
| zh | | example/mistake 说明（缺省用 sub） |
| think | | practice 提示语；缺省「先想一想，别急着看答案」；空字符串隐藏提示与间距 |

\* 可只写 `role`。

## kind → layout（整页居中）

| kind | layout |
| --- | --- |
| title | layout-title.html |
| rule | layout-rule.html |
| diagram | layout-diagram.html |
| example | layout-example.html |
| mistake | layout-mistake.html |
| practice | layout-practice.html |
| answer | layout-answer.html |
| summary | layout-summary.html |

## 排版变体（layout_variant）

同一种 kind 支持多种排版变体，通过 `layout_variant` 字段选择：

| kind | 变体 ID | 文件 | 适用场景 |
| --- | --- | --- | --- |
| rule | `"side"` | layout-rule-side.html | 左规则右示例，需要即时示范 |
| rule | `"formula"` | layout-rule-formula.html | 上公式下拆解，复杂数学公式 |
| example | `"side"` | layout-example-side.html | 左正确右易错对比 |

省略 `layout_variant` → 使用默认 layout。变体文件不存在时自动回退默认。

`example` 的 `side` 变体：左栏使用 `body`（正确示例），右栏使用独立的 `wrong_body`（错误示例），不自动生成或复用正确句子。例如：

```json
{"kind": "example", "layout_variant": "side", "header": "比较句子", "body": "He **is reading**.", "wrong_body": "He **reading**.", "narrate": "现在进行时不能漏掉 be 动词。"}
```

## chart 对象（diagram 页面专用）

```json
"chart": {
  "preset": "curve",
  "axes": {"x": "消费量 Q", "y": "边际效用 MU"},
  "range": {"xmin": 0, "xmax": 5, "ymin": 0, "ymax": 100},
  "curve": {"color": "__ACCENT__", "width": 5, "points": [...]},
  "highlights": [{"x": 1, "y": 72, "label": "Q=1", "color": "__ACCENT__"}]
}
```

| 预设 | 用途 | 必填字段 |
| --- | --- | --- |
| `curve` | 坐标曲线（经济/数学） | axes, range, curve (points 或 fn), highlights |
| `quadrant` | 四象限矩阵 | axes, labels |
| `timeline` | 时间轴 | events |

颜色 token：`__ACCENT__` / `__WRONG__` / `__CORRECT__` 自动映射到当前 skin 色值。  
详见 [`scripts/charts.py`](../scripts/charts.py)。

## `**` 高亮色（style token）

| kind | token |
| --- | --- |
| practice / mistake | wrong |
| example / answer | correct |
| rule / title / summary | accent |

## 契约

- *分镜* 字段 = 教学内容；色值/字号 ∈ `style-*.json`
- layout = 结构槽 `__HEADER__` / `__BODY__` / `__THINK__`（仅 practice） / … + 居中构图
- *闸门*：`py scripts/validate_storyboard.py <json>`（教学弧顺序 + `practice.hold>=3.0`；exit 0）
- 预览：`py scripts/make_video.py <json> --preview`（缩略图 + 溢出）；全量渲染会先跑同一预览，通过后再 TTS

> Windows 用 `py` 启动器（`python` 在 WindowsApps 桩上静默失败、零输出）；macOS/Linux 用 `python3`。
