# 分镜 JSON

权威字段表。教学义务见 [`teaching-method.md`](teaching-method.md)；样例见 `examples/now_progressing.json`。

## 顶层

| 字段 | 必填 | 说明 |
| --- | --- | --- |
| title | ✅ | 知识点名 |
| voice | ✅ | 小米 TTS：mimo_default/冰糖/茉莉/苏打/白桦/Mia/Chloe/Milo/Dean |
| style | | `teaching` / `classroom` / `explainer`；CLI `--style` 可覆盖 |
| motion | | 顶层 bool，默认 true |
| fps / width / height | | 默认 30、1280×720 |
| scenes | ✅ | 分镜数组 |

## scenes[]

| 字段 | 必填 | 说明 |
| --- | --- | --- |
| kind | ✅* | title / rule / example / mistake / practice / answer / summary |
| role | | *page-role*；可代替 kind；与 kind 同写须一致 |
| motion | | focus / pulse / zoom_in / zoom_out / none；默认见 [`motion.md`](motion.md) |
| header | ✅ | 「学习者此刻做什么」 |
| sub | 推荐 | 副题；mistake=诱因；example 可兼中文义 |
| body | ✅ | 主体；`**...**` = 高亮知识点 |
| narrate | ✅ | TTS 口语短句 |
| hold | practice | ≥3.0（样例 3.0） |
| zh | | example/mistake 说明（缺省用 sub） |

\* 可只写 `role`。

## kind → layout（整页居中）

| kind | layout |
| --- | --- |
| title | layout-title.html |
| rule | layout-rule.html |
| example | layout-example.html |
| mistake | layout-mistake.html |
| practice | layout-practice.html |
| answer | layout-answer.html |
| summary | layout-summary.html |

## `**` 高亮色（style token）

| kind | token |
| --- | --- |
| practice / mistake | wrong |
| example / answer | correct |
| rule / title / summary | accent |

## 契约

- *分镜* 字段 = 教学内容；色值/字号 ∈ `style-*.json`
- layout = 结构槽 `__HEADER__` / `__BODY__` / … + 居中构图
- *闸门*：`python scripts/validate_storyboard.py <json>`（教学弧顺序 + `practice.hold>=3.0`；exit 0）
- 预览：`python scripts/make_video.py <json> --preview`（缩略图 + 溢出）；全量渲染会先跑同一预览，通过后再 TTS
