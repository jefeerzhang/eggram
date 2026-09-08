---
name: micro-video
description: >
  教学微课：把一个知识点做成 2–3 分钟 mp4（分镜 JSON → 闸门校验 → TTS/HTML 渲染）。
  触发：给孩子做教学课、教学短视频、讲练穿插微课、某语法点/公式/定律/句型做成视频、重渲/换皮已有分镜。
---

# micro-video

产物：本目录 Skill + `examples/<point>.json` → `output/*.mp4`。

**Leading words：** *脚本硬阻断*（生成 JSON 前人眼对齐）· *分镜*（内容 IR）· *闸门*（TTS 前硬校验）· *换皮*（只改 style）· *音画锁*（hold 进音轨且等长）· *page-role*（教学弧）

三阶段流程：阶段 0 方案与用户确认（硬阻断）→ 阶段 1 分镜落盘与闸门 → 阶段 2 视频渲染。改 *分镜* 或模板后先过 *闸门* 再全量配音。

---

## 阶段 0 — 脚本方案与用户确认（硬阻断）

> **硬阻断红线**：用户提出一个微课主题/知识点后，AI **严禁直接创建/覆写分镜 JSON 或启动渲染**！
> 必须将「内容话语权」交还用户：先输出结构化教学方案，并向用户提供**可定制选项与确认点**，得到用户明确批准（或按修改意见迭代完毕）后，方可进入阶段 1。

**Done when：**

1. AI 输出完整的教学设计清单（知识点定调、一句话目标、逐页大纲表）。
2. AI 抛出 **5 个**选择题，逐一覆盖**内容深度（Q1）、例题场景（Q2）、动效节奏（Q3）、视觉声音（Q4）、讲解模式（Q5，单人/双人）**。
3. **用户明确回复选择与确认**（若提出修改，AI 重新输出调整后大纲并二次确认）。

### Steps

1. **构思教学弧**：根据知识点，遵循 [`docs/teaching-method.md`](docs/teaching-method.md) 的标准弧：`title → rule+ → example+ → mistake → practice → answer → summary`。
2. **清晰呈现脚本方案**：使用直观的 Markdown 卡片/表格向用户展现内容全貌：
   - **课题定位与目标**：明确知识点、适用对象、学完即拿走的 1 句话收获。
   - **逐页内容清单（内容把控核心）**：

     | 序号 | 角色 (role/kind) | 画面主要内容（标出 `**高亮**` 处） | 旁白草稿 (Narrate) | 互动说明 (Hold/Think) |
     | :--- | :--- | :--- | :--- | :--- |
     | 1 | title | 标题 + 副标/英译 | 吸引注意，引入主题 | - |
     | 2 | rule | 核心定义/结构式 | 拆解规则 | - |
     | 3 | example | 典型示范 + 译文 | 示范应用 | - |
     | 4 | mistake | 典型易错点 | 敲黑板，分析诱因 | - |
     | 5 | practice | 互动自测题 | 抛出问题，引导思考 | 停顿思考（默认 ≥3s） |
     | 6 | answer | 答案揭晓 + 简短原因 | 正向反馈，解释原因 | - |
     | 7 | summary | 可带走口诀/终极公式 | 总结要点，鼓励结尾 | - |

3. **环境前置预检与向用户抛出 5 个选择题（Q1–Q5，把控内容、质量、形式、对话模式）**：
   - **【前置环境检查】**：在输出大纲的同时，AI 必须先检查本地环境变量（`MIMO_API_KEY`、浏览器），若缺少 TTS Key，**必须在这一轮与选择题一同提示用户补齐**，严禁到渲染阶段才中途索要。
   - **【内容深度】Q1 教学难度与受众**：
     - A. 零基础入门（趣味口语化、生活化类比、不堆砌术语）
     - B. 进阶应试（抓考点变形、公式化拆解、强化陷阱辨析）
   - **【质量把控】Q2 选材与例题倾向**：
     - A. 高频生活实用场景（重日常沟通理解，轻松直观）
     - B. 经典考试/竞赛真题改编（重易错易混淆陷阱，提分导向）
   - **【形式节奏】Q3 动效与观看节奏**：
     - A. 快节奏动感微课（开 motion，关键知识点推拉与脉冲高亮，抓眼球）
     - B. 沉静板书讲解（关 motion 或轻微缩放，画面稳重，适合长时间专注）
   - **【视听形式】Q4 视觉皮肤与配音音色**：
     - A. `teaching`（深底橙光科技感）+ `苏打`（阳光活力男声）
     - B. `classroom`（暖白板书教研风）+ `冰糖`（温和亲切女声）
     - C. `explainer`（纸面大字解析风）+ `白桦`（沉稳专业男声）
   - **【讲解模式】Q5 单人讲解 vs 双人对话**：
     - A. 单人讲解（一个音色从头讲到尾，简洁高效）
     - B. 双人对话（男女生一问一答，如「老师讲解 + 学生提问」，更有课堂感）
     - 若选 B，需指定两个音色（如 `苏打` + `冰糖`），并在分镜中通过 `voices` 映射 + 每页 `voice` 字段分配角色
4. **硬阻断与互动修改**：
   - 停下等待用户输入。
   - **AI 必须把 Q1–Q5 五个问题全部问完、用户逐一回复后才进入阶段 1**。任何 Q 都不得以"按惯例默认"为由跳过；若 AI 跳过任一 Q，视为硬阻断失败，须重走阶段 0。
   - 用户可直接选 "AABBA" 或针对某页旁白/例题提出调整。
   - 任何改动均先在文本层面达成一致，**绝不抢跑写代码或落盘 JSON**。

---

## 阶段 1 — 写分镜

**Done when：** `examples/<point_slug>.json` 存在，且：

```bash
py scripts/validate_storyboard.py examples/<point_slug>.json
```

> Windows 用户用 `py` 启动器；macOS/Linux 用 `python3`（下文示例同此约定）。

退出码 0。

### Steps

1. 读 [`docs/teaching-method.md`](docs/teaching-method.md)，按 *page-role* 拆弧，写入 `kind`（可同写 `role`）。  
   **Done when：** 含必选弧 `title → rule+ → example+ → practice → answer → summary`；推荐在 `practice` 前有 `mistake`。
2. 填字段；字段表见 [`docs/json-schema.md`](docs/json-schema.md)。  
   **Done when：** 每段有 `header/body/narrate`；需强调处用 `**`；`practice.hold >= 3.0`；正文是教学内容（色值/字号只在 style）。  
   **body 换行规则：** 用 `<br>` 表示换行（如 `"body": "第一行<br>第二行"`），**严禁用 `\n`**——`\n` 会被原样显示为文本而非换行。  
   **图解（diagram）规则：** `kind: "diagram"` 页面通过 `chart` 对象声明式调用图表预设（`preset: "curve"` / `"quadrant"` / `"timeline"`），详见 [`scripts/charts.py`](scripts/charts.py)。  
   **排版变体：** 同一 kind 支持多种排版变体，通过 `layout_variant` 字段选择（如 rule 的 `"side"` 左规则右示例 / `"formula"` 上公式下拆解），详见 [`docs/json-schema.md`](docs/json-schema.md)。  
   **动效序列化：** `motion` 支持字符串（如 `"focus"`）或 effects 数组（如 `[{"type":"focus","delay":0},{"type":"pulse","delay":0.5}]`），详见 [`docs/motion.md`](docs/motion.md)。
3. 选定 `voice` 与 `style`（换皮见 [`docs/styles.md`](docs/styles.md)）。  
   **Done when：** 顶层字段齐全；样例对照 [`examples/now_progressing.json`](examples/now_progressing.json)。
4. 跑 *闸门*（上列命令）。  
   **Done when：** exit 0。

---

## 阶段 2 — 渲视频

> 两种入口：直接跑 `make_video.py`（小改/调试/单次），或**委托渲染 worker**（批量/CI/父代理要并行写下一份 *分镜*）：`py scripts/render_worker.py examples/<slug>.json --reuse-audio`，5 步 preflight→preview→render→verify→回传不可绕过，契约见 `.scratch/render-worker/spec.md`（map：GitHub #9）。

**Done when：** 目标 mp4 可播，且下方验收全勾。

```bash
py scripts/make_video.py examples/<point_slug>.json [output/<name>.mp4] [--style NAME] [--reuse-audio] [--no-motion] [--preview]
```

默认输出 `output/<json 主名>.mp4`。`--style` 覆盖换皮；`--reuse-audio` 按课目录 + 旁白/音色指纹复用 raw（[`docs/audio.md`](docs/audio.md)）；`--preview` 只出缩略图与溢出报告；动效见 [`docs/motion.md`](docs/motion.md)。

管线：二次 *闸门* → **预览截图/溢出**（未过则停）→ TTS/`prepare_scene_audio` → 时长核验 → motion 截帧 → ffmpeg。`--preview` 在预览后退出。

环境：Python 3.11+；Windows 用户须用 `py` 启动器（`python` 在 WindowsApps 桩上静默 exit 49、零输出），macOS/Linux 用 `python3`；playwright + imageio_ffmpeg + numpy；本机 Chrome/Edge；环境变量 `MIMO_API_KEY`（可选 `MIMO_API_URL`）。

### 验收

- *闸门* 绿（含教学弧顺序；`practice.hold >= 3.0`）
- 预览：`_build/preview/<slug>/s*.png` 无文字溢出（worker 换皮批并行时按 style 隔离为 `<slug>__<style>/`，见 #18）
- 画面：教学内容、整页居中、易错/练习可扫区分
- 动效：讲解聚焦、易错/练习轻脉冲（未 `--no-motion` 时）
- 音频：`hold` 段为静音；段间接缝干净；成片时长 ≈ Σ(旁白+hold)（*音画锁*）
- worker 模式：前两项由 5 项自动验收（`verify: [✓✓✓✓✓]`）替代人工勾选；画面内容/动效体感/音频接缝 3 项仍需人看

---

## 改哪里（branch → 文件）

| Branch | 打开 |
| --- | --- |
| 写/改一课内容 | 阶段 0 方案确认 → *分镜* JSON → *闸门* → 阶段 2 |
| *换皮* | JSON `"style"` 或 `--style`；[`docs/styles.md`](docs/styles.md) |
| 新皮 | 只加 `templates/style-<name>.json` |
| 改版式/居中槽 | `templates/layout-*.html`（色从 style 来） |
| 动效幅度/默认 | [`docs/motion.md`](docs/motion.md) + `make_video.py` |
| 卡顿/hold/拼接 | [`docs/audio.md`](docs/audio.md) + `prepare_scene_audio` |
| 字段/高亮色 | [`docs/json-schema.md`](docs/json-schema.md) |
| 教学弧/page-role | [`docs/teaching-method.md`](docs/teaching-method.md) |
| CLI 参数 / 浏览器发现 | `scripts/make_video.py`（`build_parser` / `find_browser`） |
| 委托渲染 worker | 入口 `scripts/render_worker.py`；子步骤 `scripts/worker_preflight/preview/verify.py`；契约 `.scratch/render-worker/` |
| 闸门规则 / 教学文本转义 | `scripts/make_video.py`（`validate_storyboard` / `validate_layouts` / `_escape`）+ `templates/layout-*.html` |
| 音频解码 / 缓存版本 | `scripts/make_video.py`（`decode_wav` / `_cache_hit`）+ [`docs/audio.md`](docs/audio.md) |
| 加回归测试 | `tests/test_make_video.py` |
| 跑全量回归 | `py -m pytest tests/` |

**契约：** *分镜* 只承载教学内容；style 只承载视觉 token；layout 只承载结构槽与居中构图。渲染前必过 *闸门*。
