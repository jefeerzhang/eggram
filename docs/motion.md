# motion

克制推拉/聚焦：把眼睛送到 `**` 高亮与结论。由渲染器 CSS 变量驱动；layout 不写死关键帧。

| motion | 效果 | kind 默认 |
|---|---|---|
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
