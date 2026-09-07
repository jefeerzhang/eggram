---
name: micro-video
description: >
  教学微课：把一个知识点做成 2–3 分钟 mp4（分镜 JSON → 闸门校验 → TTS/HTML 渲染）。
  触发：给孩子做教学课、教学短视频、讲练穿插微课、某语法点/公式/定律/句型做成视频、重渲/换皮已有分镜。
---

# micro-video

产物：本目录 Skill + `examples/<point>.json` → `output/*.mp4`。

**Leading words：** *分镜*（内容 IR）· *闸门*（TTS 前硬校验）· *换皮*（只改 style）· *音画锁*（hold 进音轨且等长）· *page-role*（教学弧）

两阶段可独立跑。改 *分镜* 或模板后先过 *闸门* 再全量配音。

---

## 阶段 1 — 写分镜

**Done when：** `examples/<point_slug>.json` 存在，且：

```bash
python scripts/validate_storyboard.py examples/<point_slug>.json
```

退出码 0。

### Steps

1. 读 [`docs/teaching-method.md`](docs/teaching-method.md)，按 *page-role* 拆弧，写入 `kind`（可同写 `role`）。  
   **Done when：** 含必选弧 `title → rule+ → example+ → practice → answer → summary`；推荐在 `practice` 前有 `mistake`。
2. 填字段；字段表见 [`docs/json-schema.md`](docs/json-schema.md)。  
   **Done when：** 每段有 `header/body/narrate`；需强调处用 `**`；`practice.hold >= 3.0`；正文是教学内容（色值/字号只在 style）。
3. 选定 `voice` 与 `style`（换皮见 [`docs/styles.md`](docs/styles.md)）。  
   **Done when：** 顶层字段齐全；样例对照 [`examples/now_progressing.json`](examples/now_progressing.json)。
4. 跑 *闸门*（上列命令）。  
   **Done when：** exit 0。

---

## 阶段 2 — 渲视频

**Done when：** 目标 mp4 可播，且下方验收全勾。

```bash
python scripts/make_video.py examples/<point_slug>.json [output/<name>.mp4] [--style NAME] [--reuse-audio] [--no-motion] [--preview]
```

默认输出 `output/<json 主名>.mp4`。`--style` 覆盖换皮；`--reuse-audio` 按课目录 + 旁白/音色指纹复用 raw（[`docs/audio.md`](docs/audio.md)）；`--preview` 只出缩略图与溢出报告；动效见 [`docs/motion.md`](docs/motion.md)。

管线：二次 *闸门* → **预览截图/溢出**（未过则停）→ TTS/`prepare_scene_audio` → 时长核验 → motion 截帧 → ffmpeg。`--preview` 在预览后退出。

环境：`python` + playwright + imageio_ffmpeg + numpy；本机 Chrome/Edge；环境变量 `MIMO_API_KEY`（可选 `MIMO_API_URL`）。

### 验收

- *闸门* 绿（含教学弧顺序；`practice.hold >= 3.0`）
- 预览：`_build/preview/<slug>/s*.png` 无文字溢出
- 画面：教学内容、整页居中、易错/练习可扫区分
- 动效：讲解聚焦、易错/练习轻脉冲（未 `--no-motion` 时）
- 音频：`hold` 段为静音；段间接缝干净；成片时长 ≈ Σ(旁白+hold)（*音画锁*）

---

## 改哪里（branch → 文件）

| Branch | 打开 |
| --- | --- |
| 写/改一课内容 | *分镜* JSON → *闸门* → 阶段 2 |
| *换皮* | JSON `"style"` 或 `--style`；[`docs/styles.md`](docs/styles.md) |
| 新皮 | 只加 `templates/style-<name>.json` |
| 改版式/居中槽 | `templates/layout-*.html`（色从 style 来） |
| 动效幅度/默认 | [`docs/motion.md`](docs/motion.md) + `make_video.py` |
| 卡顿/hold/拼接 | [`docs/audio.md`](docs/audio.md) + `prepare_scene_audio` |
| 字段/高亮色 | [`docs/json-schema.md`](docs/json-schema.md) |
| 教学弧/page-role | [`docs/teaching-method.md`](docs/teaching-method.md) |

**契约：** *分镜* 只承载教学内容；style 只承载视觉 token；layout 只承载结构槽与居中构图。渲染前必过 *闸门*。
