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

## 音画锁

动效由**秒语义**驱动（见上节时间语义）；旁白结束后的 `hold` 与尾垫（静音）期间画面停在末态，不再 pulse/zoom（见 [audio.md](audio.md)）。零时长旁白、零 hold 不产生除零或丢帧。
