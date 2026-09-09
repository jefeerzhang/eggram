# 动画 block 配方（hyperframes catalog 移植）

来源：[heygen-com/hyperframes](https://github.com/heygen-com/hyperframes)（Apache-2.0）。
原仓库 100+ block 配方，本目录挑 3 个**直接对应 micro-course page-role** 的。

## 选用依据

| Block | page-role | 理由 |
|---|---|---|
| `beat-freeze-cut` | `title` | 入场 push-in + freeze hit → "现在进行时"核心词重击，比纯缩放有冲击力 |
| `cinematic-zoom` | `rule` | WebGL radial-blur shader → 规则定义时"聚焦"感，配合右栏公式/例句 |
| `bar-chart-race` | `mistake` | 数据驱动 → "3 类错误占比随年级变化"或"5 个易错点答题正确率" |

未选但相邻可借鉴：
- `camcorder-hud` → `example` 页：把解题过程当成"录屏"，加 REC + 计时器
- `code-morph` / `code-diff` → `mistake` 页：错误→正确代码形变
- `kinetic-typography`（catalog 里实际是 `word-by-word` 类） → `summary` 页口诀逐字

## 单文件预览（最快验证）

每个 .html 是独立可跑的（GSAP + 字体走 CDN），直接：

```bash
# 任选其一
start templates/blocks/beat-freeze-cut.html
start templates/blocks/cinematic-zoom.html
start templates/blocks/bar-chart-race.html
```

浏览器里自动循环 GSAP timeline，看动效节奏和质感。

## 用 playwright 录 6/4/12 秒预览 mp4（无音轨）

适合先做"对比 mp4"给另一个 agent / 给自己看：

```python
# preview_block.py —— 临时脚本，用完删
import asyncio, os
from playwright.async_api import async_playwright

BLOCKS = {
    "beat-freeze-cut": 6,
    "cinematic-zoom":  4,
    "bar-chart-race":  12,
}

async def record(name, dur):
    async with async_playwright() as p:
        browser = await p.chromium.launch()
        page = await browser.new_page(viewport={"width": 1920, "height": 1080})
        await page.goto(f"file://{os.path.abspath(f'templates/blocks/{name}.html')}")
        await page.wait_for_timeout(500)  # GSAP 加载 + 首帧稳定
        await page.screenshot(path=f"output/_preview_{name}_0000.png", full_page=False)
        # 简单做法：每秒抓一帧示意
        for sec in range(1, dur + 1):
            await page.wait_for_timeout(1000)
            await page.screenshot(path=f"output/_preview_{name}_{sec:04d}.png")
        await browser.close()

async def main():
    for name, dur in BLOCKS.items():
        await record(name, dur)

asyncio.run(main())
```

跑完用 ffmpeg 把帧拼起来：

```bash
ffmpeg -framerate 1 -i output/_preview_<name>_%04d.png -c:v libx264 -pix_fmt yuv420p output/_preview_<name>.mp4
```

## 接入 make_video.py 的三种路径

| 路径 | 改动量 | 适用 |
|---|---|---|
| **A. 整页换肤** | 最小 | `title` / `summary` 这类 1-2 页短的，直接整页用 block 的 HTML 替换你现在的 PIL 渲染。playwright 截帧后照常 ffmpeg mux。 |
| **B. block 局部嵌入** | 中 | 把 block 的 `<style>` + 关键 DOM 抠出来塞进你现有 HTML 模板，删掉 `data-composition-id` 包装，让它作为页面一个 `<div>` 存在。GSAP timeline 改用你 `narr_frames / fps` 反算的 `duration` 驱动。 |
| **C. 状态导出 + 帧重建** | 最大 | 在 playwright 里 `timeline.seek(t)` 取每帧 DOM 状态（CSS computed style + 元素 transform），按你 `frame_motion_state(frame, fps)` 的接口喂回去。完全保留你 TTS-first 的契约，但实现成本最高。 |

**推荐先走 A**，把 3 个 block 各自做一支独立 mp4 试看，验证"动画够不够好"再决定 B/C。

## 已知坑

1. **GSAP CDN**：依赖 `cdn.jsdelivr.net`，离线环境需要自托管 GSAP 3.14+。
2. **WebGL**：`cinematic-zoom` 需要 GPU 加速，已内置 GSAP-only 降级（GPU 不可用时简单缩放）。
3. **字体**：`beat-freeze-cut` / `bar-chart-race` 用 Google Fonts 中文会回退到系统字体，建议本地放 Noto Sans SC。
4. **`** 高亮`**：当前 block 没有适配你 JSON 里的 `**word**` 标记。B 路径接入时要单独写一个把 `**` 转 GSAP `SplitText` 的桥。
5. **block 是 1920x1080 6/4/12s**：跟你 `720p 30fps` 主流水线不直接对齐，要么改 make_video.py 走两套分辨率，要么按比例缩 block 内部所有 px 值。

## 下一步

跑一遍"单文件预览"看动效，决定哪些 block 进项目。如果觉得 OK：

1. 把 `output/_preview_*.mp4` 给我看，我帮你判定 page-role 适配度
2. 选一条接入路径（A/B/C），写 make_video.py 的改造计划
3. 改完后用同一分镜（`examples/now_progressing.json`）出一支旧版 + 一支新版对比 mp4

## 许可证

三个 block 均为 Apache-2.0（原仓库 LICENSE 文件）。保留原作者声明即可商用。

## 集成现状（#27，Path A 已落地）

- **唯一接缝**：`scripts/make_video.py` 的 `BLOCK_BY_KIND` 查找表——`title`→
  beat-freeze-cut、`rule`→cinematic-zoom、`mistake`→bar-chart-race；
  其余 kind 走原静态布局。分镜顶层 `"blocks": false` 可整支关闭。
- **数据注入**：集成层把 page 数据经 `application/json` + `JSON.parse` 写入
  `window.__BLOCK_CONFIG`（`<` 转义为 `\u003c`，防 `</script>` 打断）；block
  里 `Object.assign` 合并进自己的 CONFIG——title 用 header/sub，
  rule 用 header/sub/body（纯文本换行，模板侧 textContent + `<br>`，不用
  `innerHTML`；`**高亮**` 按 out-of-scope 约定剥成纯文本），
  mistake v1 用 block 内置样例数据（schema 的 `mistake-data` 扩展待后续）。
- **帧驱动**：block 的 GSAP timeline 以 `paused` 建立（`window.__timelines`），
  渲染逐帧 `tl.time(min(k/fps, block 时长))` 驱动，跑完一遍后 hold 末态到旁白
  结束（音画锁不受影响；帧数仍由音频决定）。
- **分辨率**：pipeline 默认改出 1080p（`width`/`height` 缺省 1920×1080，
  `docs/json-schema.md`）；分镜显式钉其他分辨率时 block 整体等比缩放到视口。
- **失败回退**：block 初始化失败（CDN 不可达 / JS 报错）打印 WARN 并回退该页
  静态布局，单页失败不阻断整支视频。
- **预览闸门**：block 页不做静态布局溢出探测；改为根节点存在且在视口内有
  可见盒模型（`block_preview_check`）。
- **验收**：`templates/blocks/_smoke.py` 独立烟雾（timeline 就绪 + 根节点
  1920px）；端到端在 `tests/test_render_worker.py`（block 页进成片、manifest
  记录 scene.block、1080p、回退路径）。
