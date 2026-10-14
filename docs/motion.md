# motion

克制推拉/聚焦：把眼睛送到 `**` 高亮与结论。由渲染器 CSS 变量驱动；layout 不写死关键帧。

| motion | 效果 | kind 默认 |
| --- | --- | --- |
| `focus` | 轻推近 + 高亮一次聚焦后微保持 | rule / example |
| `pulse` | 高亮两下轻跳 | mistake / practice |
| `zoom_in` | 缓慢拉近 | title / answer |
| `zoom_out` | 略近落到正常 | summary |
| `none` | 静止 | 显式关闭 |

省略 scene.`motion` → 用上表默认。覆盖：

```json
{ "kind": "practice", "motion": "pulse" }
```

全书关：顶层 `"motion": false`，或 `--no-motion`。

幅度目标：整页约 3%–6% 推拉，高亮约 14%–16% 脉冲。

## 动效序列化（effects 数组）

一个元素支持多动效叠加，用数组声明：

```json
{
  "kind": "rule",
  "motion": [
    {"type": "focus", "delay": 0},
    {"type": "pulse", "delay": 0.5}
  ]
}
```

- `type`：动效类型（focus / pulse / zoom_in / zoom_out / none）
- `delay`：延迟秒数（视频时间，相对段首；默认 0）。动效在 delay 后的**剩余旁白时间内**完成
- 叠加规则：scale/hl/glow 取各动效在对应时刻的最大值
- 向后兼容：单字符串 `"motion": "focus"` 仍然有效

## 时间语义（音画锁的时间轴）

- 动效时钟以**秒**计：第 `k` 帧的 elapsed = `k/fps`，旁白终点 = `narr_frames/fps`（由旁白样本数按 fps 向上取整）。
- `delay` 按秒解释，与 fps 无关：同一 delay 在不同 fps 下对应相同秒数（允许一帧量化误差）。
- `delay ≥ 旁白时长`（延迟不早于旁白结束）：该动效不启动，画面保持初态。
- hold 与尾垫期间 elapsed 已达旁白终点 → 冻结在动效末态（见 [audio.md](audio.md)）。

预览（TTS 之前）没有真实旁白时长，溢出探测按各动效**自身可达窗口**（delay 后 1 秒内完成）采样 0..1，延迟动效的放大末态不会被漏检。

## 公式页分步动效

叠在整页动效之上，共用同一条秒语义时钟（不需要新 JSON 字段，也不需要写 `motion`）。
仅 `kind: "rule"` + `layout_variant: "formula"` 且 `formula.parts` 非空时启用；
把该页旁白时长按比例切成三段：

| 区间 | 占旁白时长 | 画面 |
| --- | --- | --- |
| 入场 | 0–15% | 公式卡从下方 8px 抬起落位，阴影随之张开；分式线宽度 0；分项全暗 |
| 主式 | 15–40% | 分式线**匀速**描出（scaleX 0→1），主式轻放大 1.04；分项仍全暗 |
| 分项 | 40–100% | 余下时长按 `parts` 数量均分，逐项点亮；当前项全亮，**已讲过的停在半亮**，未讲到的暗 |

- 抬起用 `ease_out_cubic`（先快后缓，与 `zoom_in` 手感一致）；分式线刻意保持线性——笔画等速才像"描"。
- 透明度三档：当前 1.0、已讲过 0.725、未讲到 0.45；入场与主式两段还没有"当前项"，分项一律 0.45。
- 点亮顺序 = `parts` 数组顺序，靠 DOM 上的 `data-part-id` 匹配，因此 `id` 页内唯一是硬要求。
- `hold` 与尾垫期间冻在末态（最后一项亮着），不会在旁白结束后继续推进。
- 该页若是静态（`motion: "none"` 或只有一帧），整页复用同一张截图，直接取末态，不会卡在入场中途。
- 旧双步 `formula`（无 `parts`）不参与分步动效，分项常亮。

变量与实现在 [`scripts/storyboard_gate.py`](../scripts/storyboard_gate.py)（`formula_motion_vars` / `apply_motion_css_vars` / `MOTION_CSS`）。

## 结构、操作、纠错的分步展示

仅用于 `rule/structure`、`example/steps`、`mistake/compare` 的 `visual.items`，不新增 motion 类型。开启 motion 时，旁白总时长按项目数量均分；每项在其窗口的前半段线性点亮，后半段保持。结构部件与操作步骤从淡显到全亮；纠错先完整展示错误，再逐行揭示修正及原因。先前点亮的内容保持全亮。

- 与整页动效使用同一时钟：`elapsed = k/fps`，`duration = narr_frames/fps`。
- `hold` 和尾垫冻结末态；超出旁白时长不继续推进。
- 顶层 `motion: false`、`--no-motion`、每页 `motion: "none"`、单帧页均完整静态展示。
- 分步时间不读取 effects 的 `delay`；该字段只控制已有整页动效。
- 预览无真实音频，展示完整末态并沿用整页动效溢出采样。
- 数组順序须与旁白顺序一致；这是总时长比例动画，不是逐句音画对齐。

实现：[`scripts/visual_layouts.py`](../scripts/visual_layouts.py) 的 `visual_reveal_levels` / `apply_visual_state`；CSS 在 `templates/layout-visual.html`，渲染入口在 `scripts/make_video.py`。

## 音画锁

动效由**秒语义**驱动（见上节时间语义）；旁白结束后的 `hold` 与尾垫（静音）期间画面停在末态，不再 pulse/zoom（见 [audio.md](audio.md)）。零时长旁白、零 hold 不产生除零或丢帧。
