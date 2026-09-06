# 换皮（style）

*换皮* = 只改 `templates/style-*.json`（或 JSON/`--style`），layout 与 *分镜* 不动。*page-role* 见 [`teaching-method.md`](teaching-method.md)。

| style | 文件 | 观感 | 选用 |
|---|---|---|---|
| `teaching` | style-teaching.json | 深底橙强调 | 默认短视频 |
| `classroom` | style-classroom.json | 暖白蓝强调 | 课堂/板书 |
| `explainer` | style-explainer.json | 浅纸青蓝、字更大 | 类比/纠错 |

```json
"style": "classroom"
```

```bash
python scripts/make_video.py examples/now_progressing.json out.mp4 --style explainer --reuse-audio
```

新皮：新增 `templates/style-<name>.json`，token 齐备（palette / typography / exercise）；layout 继续只服务 kind。

颜色工作（accent / correct / wrong / ink_sub）与 [`teaching-method.md`](teaching-method.md) 同表——以 style 文件为注入源。
