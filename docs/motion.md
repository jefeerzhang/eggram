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
- `delay`：延迟秒数（相对于段内进度，默认 0）
- 叠加规则：scale/hl/glow 取各动效在对应时刻的最大值
- 向后兼容：单字符串 `"motion": "focus"` 仍然有效

## 音画锁

动效进度由**旁白对应帧**驱动；旁白结束后的 `hold` 与尾垫（静音）期间画面停在末态，不再 pulse/zoom（见 [audio.md](audio.md)）。零时长旁白、零 hold 不产生除零或丢帧。
