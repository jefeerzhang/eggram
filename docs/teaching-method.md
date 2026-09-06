# page-role（教学弧）

来源灵感：[ppt-master `workshop-teaching`](https://github.com/hugohe3/ppt-master)。eggram 把方法落成 *分镜* `kind`；视觉用 *换皮*，结构用 layout——**Style ≠ Layout**。

## 论证流

目标 → 最小概念 → 完整示范 → 常见错误 → 理解检查 → 揭晓 → 可带走公式。  
一页一个动作或一个概念；概念出现在马上要用之时。

## role ↔ kind ↔ 内容义务

| role | kind | 义务 |
|---|---|---|
| `learning_objective` | `title` | header=语法点；sub=英文名或一句话目标 |
| `concept_anchor` | `rule` | body 用 `**` 标结构/变形；单概念 |
| `worked_demo` | `example` | 英文句 + `**`；sub/zh=中文义 |
| `common_mistake` | `mistake` | 错误写法 + `**` 错点；sub/zh=诱因 |
| `understanding_check` | `practice` | 应用判断句 + `**`；`hold>=3.0` |
| `check_reveal` | `answer` | 正确句 + `**`；sub=一句原因 |
| `recap` | `summary` | body=公式；sub=下一动作/再见 |

写 `kind`，或写 `role`（渲染器映射）。两者同写须一致。

## 教学弧

必选：`title → rule+ → example+ → practice → answer → summary`  
推荐：`practice` 前加 `mistake`。

## 颜色工作（只在 style）

| token | 工作 |
|---|---|
| accent | 新 / 变 / 强调 |
| correct | 正确形式 |
| wrong | 错误 / 易错 |
| ink_sub | 次要说明（只出现在 style，不当正文） |

字段与 layout 映射：[`json-schema.md`](json-schema.md)。*换皮*：[`styles.md`](styles.md)。
