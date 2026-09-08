# 换皮（style）

*换皮* = 只改 `templates/style-*.json`（或 JSON/`--style`），layout 与 *分镜* 不动。*page-role* 见 [`teaching-method.md`](teaching-method.md)。

| style | 文件 | 观感 | 选用 |
| --- | --- | --- | --- |
| `teaching` | style-teaching.json | 深底橙强调 | 默认短视频 |
| `classroom` | style-classroom.json | 暖白蓝强调 | 课堂/板书 |
| `explainer` | style-explainer.json | 浅纸青蓝、字更大 | 类比/纠错 |

```json
"style": "classroom"
```

```bash
py scripts/make_video.py examples/now_progressing.json out.mp4 --style explainer --reuse-audio
# 先看页：py scripts/make_video.py examples/now_progressing.json --preview --style explainer
```

> Windows 用 `py` 启动器；macOS/Linux 用 `python3`。

新皮：新增 `templates/style-<name>.json`，token 齐备（palette / typography / exercise）；layout 继续只服务 kind。

## palette 字段格式

palette 支持两种格式（向后兼容）：

**字符串格式（旧）：**

```json
"accent": "#ffb020"
```

**对象格式（新，推荐）：**

```json
"accent": {"hex": "#ffb020", "provenance": "fact", "role": "新知识点强调 / 高亮"}
```

- `hex`：实际色值
- `provenance`：`fact`（官方确定色）/ `approx`（推导近似色）
- `role`：语义角色说明

## 颜色语义角色

| token | 语义 | CSS 变量 |
| --- | --- | --- |
| accent | 新知识点强调 / 高亮 | `__ACCENT__` |
| correct | 正确形式 / 正向反馈 | `__CORRECT__` |
| wrong | 错误形式 / 易错警示 | `__WRONG__` |
| warning | 警告 / 需注意 | `__WARNING__` |
| info | 提示 / 补充信息 | `__INFO__` |
| highlight | 文本高亮（同 accent） | `__HIGHLIGHT__` |
| muted | 极次要 / 禁用态 | `__MUTED__` |
| ink_sub | 次要说明文字 | `__INK_SUB__` |
