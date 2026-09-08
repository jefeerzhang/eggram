# page-role（教学弧）

来源灵感：[ppt-master `workshop-teaching`](https://github.com/hugohe3/ppt-master)。micro-course 把方法落成 *分镜* `kind`；视觉用 *换皮*，结构用 layout——**Style ≠ Layout**。

## 论证流

目标 → 最小概念 → 完整示范 → 常见错误 → 理解检查 → 揭晓 → 可带走公式。  
一页一个动作或一个概念；概念出现在马上要用之时。

## role ↔ kind ↔ 内容义务

| role | kind | 义务 |
| --- | --- | --- |
| `learning_objective` | `title` | header=知识点；sub=英文名/公式/一句话目标 |
| `concept_anchor` | `rule` | body 用 `**` 标结构/变形；单概念 |
| `worked_demo` | `example` | 英文句 + `**`；sub/zh=中文义 |
| `common_mistake` | `mistake` | 错误写法 + `**` 错点；sub/zh=诱因 |
| `understanding_check` | `practice` | 应用判断句 + `**`；`hold>=3.0`；think=练习提示语，空串隐藏 |
| `check_reveal` | `answer` | 正确句 + `**`；sub=一句原因 |
| `recap` | `summary` | body=公式；sub=下一动作/再见 |

写 `kind`，或写 `role`（渲染器映射）。两者同写须一致。

## 教学弧

必选：`title → rule+ → example+ → practice → answer → summary`  
推荐：`practice` 前加 `mistake`。

## 对话模式（双音色）

支持男女生对话式教学，通过 `voices` 映射 + 每页 `voice` 覆盖实现：

```json
{
  "voice": "苏打",
  "voices": {"narrator": "苏打", "student": "冰糖"},
  "scenes": [
    {"kind": "rule", "narrate": "边际效用就是...", "voice": "narrator"},
    {"kind": "practice", "narrate": "老师，为什么第二杯半价呢？", "voice": "student", "hold": 3.0},
    {"kind": "answer", "narrate": "好问题！正因为边际效用递减...", "voice": "narrator"}
  ]
}
```

- `voices`：角色 ID → 音色名映射（顶层定义）
- 每页 `voice`：可写角色 ID（如 `"narrator"`）或直接写音色名（如 `"苏打"`）
- 省略 `voice` → 使用顶层 `voice` 默认值
- 音频缓存按 `voice|narrate` 指纹隔离，换音色自动重 TTS

## 颜色工作（只在 style）

| token | 工作 |
| --- | --- |
| accent | 新 / 变 / 强调 |
| correct | 正确形式 |
| wrong | 错误 / 易错 |
| ink_sub | 次要说明（只出现在 style，不当正文） |

字段与 layout 映射：[`json-schema.md`](json-schema.md)。*换皮*：[`styles.md`](styles.md)。
