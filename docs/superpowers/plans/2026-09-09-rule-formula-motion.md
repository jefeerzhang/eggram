# Rule Formula Motion (Phase 2) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在已有 `formula` / `parts` / `data-part-id` 上，为 `rule`+`formula` 页增加轻量分步动效（卡抬起 → 主式 focus → 逐 part 高亮），不改 JSON schema、不上 #27。

**Architecture:** 扩展 `MOTION_CSS` 与 `apply_motion_css_vars`，新增 `formula_motion_vars(parts, elapsed, duration)` 按秒语义输出 `--m-card-*` / `--m-frac-bar` / `--m-active-part`；`make_video` 渲染循环在 formula 页叠加这些变量。默认把旁白时长切成：入场 → 主式 → 均分 parts；显式 `motion` 数组仍驱动整页 scale/hl。

**Tech Stack:** Python、`storyboard_gate.py`、`make_video.py`、CSS 变量、`pytest`（`py`）。

**Spec:** [`docs/superpowers/specs/2026-09-09-rule-formula-layout-design.md`](../specs/2026-09-09-rule-formula-layout-design.md) §4  
**Depends on:** Phase 1（已在 `main`）

## Global Constraints

- 无新 JSON 字段；用 `parts[].id` + DOM `data-part-id`
- CSS 变量 + 秒语义（与 `frame_motion_state` 同一时钟）；hold 冻末态
- 幅度克制：卡位移 ≤8px；非激活 part 透明度约 0.45；无 CDN/GSAP/WebGL
- 仅 `rule` + `layout_variant: formula` 且存在 `formula.parts`（长度≥1）时启用公式动效
- 不做 ASR 对齐、KaTeX、#27、改默认分辨率
- Windows：`py -m pytest`；中文 conventional commits

## File map

| File | Responsibility |
| --- | --- |
| `scripts/storyboard_gate.py` | `MOTION_CSS`、`formula_motion_vars`、`apply_motion_css_vars` 扩展 |
| `scripts/make_video.py` | 渲染循环传入 parts + 叠加 formula 变量 |
| `templates/layout-rule-formula.html` | 绑定新 CSS 变量（卡/分式线/part） |
| `tests/test_make_video.py` | 时间切分与 CSS 变量单测 |
| `docs/motion.md` | 公式页默认时间线说明 |

---

### Task 1: `formula_motion_vars` 纯函数（TDD）

**Files:**
- Modify: `scripts/storyboard_gate.py`
- Test: `tests/test_make_video.py`
- Re-export: `make_video.py` 已有 `from storyboard_gate import ...` 时一并导出（若测试经 `mv.` 访问）

**Interfaces:**
- Produces: `formula_motion_vars(parts: list[dict], elapsed: float, duration: float) -> dict[str, float|str]`
  - Keys: `card_y` (px, 0..8), `card_elev` (0..1), `frac_bar` (0..1), `active_part` (part id 或 `""` / `"__main__"`)
- Consumes: 无；纯函数

默认时间线（相对 `duration`，`duration<=0` 时全冻初态）：

| 区间 | 进度 t∈[0,1] 内 | 输出 |
| --- | --- | --- |
| 入场 | 0 ≤ u < 0.15 | card_y: 8→0, card_elev: 0→1, frac_bar: 0, active=`""` |
| 主式 | 0.15 ≤ u < 0.40 | card 末态, frac_bar: 0→1, active=`"__main__"` |
| parts | 0.40 ≤ u ≤ 1 | 均分剩余；当前段 active=`parts[i].id`；frac_bar=1 |

`u = min(elapsed, duration) / duration`（duration>0）。

- [ ] **Step 1: Write failing tests**

```python
def test_formula_motion_vars_timeline_phases():
    parts = [{"id": "num"}, {"id": "den"}]
    # 入场中点
    v0 = sg.formula_motion_vars(parts, 0.075, 1.0)
    assert v0["active_part"] == ""
    assert 0 < v0["card_y"] <= 8
    assert v0["frac_bar"] == 0
    # 主式区
    v1 = sg.formula_motion_vars(parts, 0.25, 1.0)
    assert v1["active_part"] == "__main__"
    assert v1["card_y"] == 0
    assert v1["frac_bar"] > 0
    # 第一 part（0.40–0.70）
    v2 = sg.formula_motion_vars(parts, 0.50, 1.0)
    assert v2["active_part"] == "num"
    assert v2["frac_bar"] == 1.0
    # 第二 part
    v3 = sg.formula_motion_vars(parts, 0.85, 1.0)
    assert v3["active_part"] == "den"
    # hold：elapsed > duration 冻末态
    v4 = sg.formula_motion_vars(parts, 2.0, 1.0)
    assert v4["active_part"] == "den"
    assert v4["card_y"] == 0


def test_formula_motion_vars_zero_duration():
    v = sg.formula_motion_vars([{"id": "a"}, {"id": "b"}], 0.0, 0.0)
    assert v["active_part"] == ""
    assert v["card_y"] == 8
```

- [ ] **Step 2: Run — expect FAIL**

`py -m pytest tests/test_make_video.py::test_formula_motion_vars_timeline_phases tests/test_make_video.py::test_formula_motion_vars_zero_duration -v`

- [ ] **Step 3: Implement `formula_motion_vars`**

```python
def formula_motion_vars(parts, elapsed_seconds, duration_seconds):
    """公式页分步动效变量（秒语义）。parts 为 [{id,...}, ...]。"""
    parts = [p for p in (parts or []) if str(p.get("id") or "").strip()]
    duration = max(0.0, float(duration_seconds))
    elapsed = max(0.0, float(elapsed_seconds))
    if duration <= 0:
        return {"card_y": 8.0, "card_elev": 0.0, "frac_bar": 0.0, "active_part": ""}
    u = min(elapsed, duration) / duration
    if u < 0.15:
        t = u / 0.15
        return {
            "card_y": 8.0 * (1.0 - t),
            "card_elev": t,
            "frac_bar": 0.0,
            "active_part": "",
        }
    if u < 0.40:
        t = (u - 0.15) / 0.25
        return {
            "card_y": 0.0,
            "card_elev": 1.0,
            "frac_bar": t,
            "active_part": "__main__",
        }
    if not parts:
        return {
            "card_y": 0.0,
            "card_elev": 1.0,
            "frac_bar": 1.0,
            "active_part": "__main__",
        }
    # parts 区
    w = (1.0 - 0.40) / len(parts)
    i = min(len(parts) - 1, int((u - 0.40) / w)) if w > 0 else len(parts) - 1
    return {
        "card_y": 0.0,
        "card_elev": 1.0,
        "frac_bar": 1.0,
        "active_part": str(parts[i]["id"]),
    }
```

- [ ] **Step 4: Run — PASS**
- [ ] **Step 5: Commit**

```bash
git add scripts/storyboard_gate.py tests/test_make_video.py scripts/make_video.py
git commit -m "feat(motion): 增加 formula_motion_vars 分步时间线"
```

---

### Task 2: CSS 变量接线（MOTION_CSS + layout + apply）

**Files:**
- Modify: `scripts/storyboard_gate.py`（`MOTION_CSS`、`apply_motion_css_vars`）
- Modify: `templates/layout-rule-formula.html`
- Test: `tests/test_make_video.py`（断言 MOTION_CSS / layout 含变量名；可选 evaluate 单测 mock）

**Interfaces:**
- Extends `apply_motion_css_vars(page, scale, hl, glow, formula=None)`  
  `formula` 为 `formula_motion_vars` 的 dict 或 `None`
- CSS:
  - `.formula-card { transform: translateY(var(--m-card-y, 0px)); box-shadow: ... calc(var(--m-card-elev, 0) * ...) }`
  - `.formula-bar { transform: scaleX(var(--m-frac-bar, 1)); transform-origin: center }`
  - `.step { opacity: calc(0.45 + 0.55 * var(--m-part-on, 1)) }` 经 JS 按 `data-part-id` 设 `--m-part-on`
  - `[data-formula-main]` 在 active=`__main__` 时用现有 `--m-hl` 或额外 class

- [ ] **Step 1: Failing test — MOTION_CSS / layout 含钩子**

```python
def test_formula_motion_css_hooks_present():
    assert "--m-card-y" in sg.MOTION_CSS
    assert "--m-frac-bar" in sg.MOTION_CSS
    raw = open("templates/layout-rule-formula.html", encoding="utf-8").read()
    assert "var(--m-card-y" in raw or "--m-card-y" in sg.MOTION_CSS
    assert "formula-card" in raw
```

（卡片样式可写在 MOTION_CSS 里用 `.formula-card` 选择器，layout 可不重复。）

- [ ] **Step 2: Run FAIL → Step 3 implement**

`MOTION_CSS` 追加：

```css
  .formula-card{
    transform: translateY(var(--m-card-y, 0px));
    box-shadow: 0 calc(4px + var(--m-card-elev, 0) * 8px) calc(20px + var(--m-card-elev, 0) * 12px) rgba(0,0,0,0.22);
    will-change: transform, box-shadow;
  }
  .formula-bar{
    transform: scaleX(var(--m-frac-bar, 1));
    transform-origin: center center;
    will-change: transform;
  }
  .step[data-part-id]{
    opacity: calc(0.45 + 0.55 * var(--m-part-on, 1));
    transition: none;
  }
  [data-formula-main]{
    transform: scale(var(--m-formula-hl, 1));
    transform-origin: center center;
  }
```

`apply_motion_css_vars`：

```python
def apply_motion_css_vars(page, scale, hl, glow, formula=None):
    page.evaluate(
        """([s, h, g, f]) => {
          const b = document.body;
          b.style.setProperty('--m-scale', String(s));
          b.style.setProperty('--m-hl', String(h));
          b.style.setProperty('--m-glow', String(g));
          if (!f) {
            b.style.setProperty('--m-card-y', '0px');
            b.style.setProperty('--m-card-elev', '0');
            b.style.setProperty('--m-frac-bar', '1');
            b.style.setProperty('--m-formula-hl', '1');
            document.querySelectorAll('.step[data-part-id]').forEach(el => {
              el.style.setProperty('--m-part-on', '1');
            });
            return;
          }
          b.style.setProperty('--m-card-y', (f.card_y || 0) + 'px');
          b.style.setProperty('--m-card-elev', String(f.card_elev || 0));
          b.style.setProperty('--m-frac-bar', String(f.frac_bar || 0));
          const active = f.active_part || '';
          b.style.setProperty('--m-formula-hl', active === '__main__' ? '1.04' : '1');
          document.querySelectorAll('.step[data-part-id]').forEach(el => {
            const on = (!active || active === '__main__' || el.getAttribute('data-part-id') === active) ? '1' : '0';
            // 主式阶段：parts 全半透明；空 active 入场：全半透明；匹配：亮
            let v = '0';
            if (!active) v = '0';
            else if (active === '__main__') v = '0';
            else if (el.getAttribute('data-part-id') === active) v = '1';
            else v = '0';
            el.style.setProperty('--m-part-on', v);
          });
        }""",
        [round(scale, 4), round(hl, 4), round(glow, 4), formula],
    )
```

（入场 `active=""` 时 parts 全暗；主式时 parts 暗；匹配 id 时亮——与 §4「其它项略降透明」一致。）

- [ ] **Step 4: 更新所有 `apply_motion_css_vars` 调用点** 保持兼容（`formula` 默认 None）
- [ ] **Step 5: Commit**

`feat(motion): 公式页 CSS 变量与 apply 接线`

---

### Task 3: `make_video` 渲染循环叠加

**Files:**
- Modify: `scripts/make_video.py`（成片循环 + preview 探测可选）
- Test: 单元测「给定 scene 提取 parts + 调用 formula_motion_vars」的小 helper，或 monkeypatch 计数

**Interfaces:**
- Helper: `formula_parts_for_motion(sc) -> list|None`  
  仅当 `resolve_kind(sc)=="rule"` 且 `layout_variant=="formula"` 且 `isinstance(formula, dict)` 且 `parts` 为 list 时返回 parts，否则 `None`

- [ ] **Step 1: Test helper**

```python
def test_formula_parts_for_motion_only_on_formula_rule():
    assert sg.formula_parts_for_motion({
        "kind": "rule", "layout_variant": "formula",
        "formula": {"parts": [{"id": "a", "label": "A", "text": "t"},
                             {"id": "b", "label": "B", "text": "t"}]},
    }) == [{"id": "a", "label": "A", "text": "t"}, {"id": "b", "label": "B", "text": "t"}]
    assert sg.formula_parts_for_motion({"kind": "rule", "body": "x"}) is None
```

- [ ] **Step 2–3: Implement helper + wire render loop**

在 `make_video.py` 逐帧处（现有 `apply_motion_css_vars(page, *frame_motion_state(...))`）：

```python
fparts = formula_parts_for_motion(sc)
fvars = (
    formula_motion_vars(fparts, k / float(FPS), narr_frames / float(FPS))
    if fparts is not None
    else None
)
# 旁白帧用 narr；hold 帧 elapsed 仍用 frame_motion_state 的冻结语义：
# 对 formula 用 min(k, narr_frames) / FPS 与 duration=narr/FPS，与 frame_motion_state 一致
duration = narr_frames_list[i] / float(FPS)
elapsed = min(k, narr_frames_list[i]) / float(FPS)
scale, hl, glow = frame_motion_state(motion, k, FPS, narr_frames_list[i])
fvars = formula_motion_vars(fparts, elapsed, duration) if fparts is not None else None
apply_motion_css_vars(page, scale, hl, glow, fvars)
```

静态帧分支（`is_static`）同样传 `formula_motion_vars(..., 0, 1)` 或末态——**应用末态**（duration 内 u=1）以免静帧停在入场：`formula_motion_vars(fparts, 1.0, 1.0)`。

Preview 溢出探测：保持现有；不必每态扫 formula 动效（YAGNI）。可选：探测时对 active 各 part 采一次——本 plan **不做**。

- [ ] **Step 4: Commit**

`feat(renderer): 成片循环叠加公式分步动效`

---

### Task 4: 文档 + 回归

**Files:** `docs/motion.md`；可选 `docs/formulas.md` 一句链到 motion

- [ ] **Step 1: `docs/motion.md` 增加「公式页默认时间线」表（入场 0–15% / 主式 15–40% / parts 均分）**
- [ ] **Step 2: `py -m pytest tests/test_make_video.py -q`**
- [ ] **Step 3: 手工 `--preview` 可选；有浏览器时对 `.scratch/formula_demo.json` 全渲抽 3 帧肉眼看（报告即可）**
- [ ] **Step 4: Commit** `docs(motion): 说明公式页分步动效时间线`

---

## Out of scope

- 新 motion type 字符串、JSON schema 新字段  
- 按旁白词对齐、GSAP、#27  
- 非 formula 页的拟物  

## Spec coverage

| §4 项 | Task |
| --- | --- |
| 卡抬起 | 1–2 |
| 主式 focus | 1–2（`__main__` + `--m-formula-hl`） |
| 逐 part 高亮 | 1–3 |
| hold 冻末态 | 1 + 3 |
| 无新 JSON | 全局 |
| motion.md | 4 |
