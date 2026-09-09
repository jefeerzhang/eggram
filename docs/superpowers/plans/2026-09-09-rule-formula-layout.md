# Rule Formula Layout (Phase 1) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 让 `kind: rule` + `layout_variant: formula` 支持结构化 `formula`（`display` / `num` / `den` / `parts`），渲染出分式主式与分项拆解；无 `formula` 的旧分镜行为不变。

**Architecture:** 在 `storyboard_gate.py` 增加校验与 HTML 片段构建（`build_formula_main_html` / `build_formula_parts_html`），`render_html` 注入 `__FORMULA_MAIN__` / `__PARTS__`；重写 `layout-rule-formula.html` 消费这两个槽；文档与单测对齐。不动 worker、默认分辨率、其它 kind。第二期动效不在本 plan。

**Tech Stack:** Python 3.11+、`scripts/storyboard_gate.py`、HTML/CSS layout、`pytest`（Windows 用 `py`）。

**Spec:** [`docs/superpowers/specs/2026-09-09-rule-formula-layout-design.md`](../specs/2026-09-09-rule-formula-layout-design.md)

## Global Constraints

- 仅 `rule` + `layout_variant: "formula"`；其它 kind 上的 `formula` → warn
- 文本经 `_escape` / `highlight_body`；白名单仅 `<br>` / `<sub>` / `<sup>` / `**`
- 有 `formula` 时 `body` 可空；`body` 非空 → warn「以 formula 为准，body 忽略」
- `num`+`den` 齐全或 `display` 非空；`parts` 若有则长度 2–4，`id` 唯一
- 无 `formula` → 与现网一致（仍要求非空 `body`；主式=body；分项区兼容旧 zh/badge 两步）
- 不做 KaTeX、#27、改 720p 默认、worker 协议
- Windows：`py -m pytest ...`；提交信息用中文 conventional commits

## File map

| File | Responsibility |
| --- | --- |
| `scripts/storyboard_gate.py` | `validate_formula_scene`、构建主式/分项 HTML、`render_html` 槽位、layout 契约槽 |
| `templates/layout-rule-formula.html` | 分式卡 + parts 网格；`data-part-id` 钩子 |
| `tests/test_make_video.py` | 闸门 / 渲染 HTML 断言 |
| `docs/json-schema.md` | 字段表 |
| `docs/formulas.md` | 结构化写法 |
| `SKILL.md` | Context pointer（若需） |

---

### Task 1: 闸门 — `formula` 校验（TDD）

**Files:**
- Modify: `scripts/storyboard_gate.py`（`validate_storyboard` 内）
- Test: `tests/test_make_video.py`

**Interfaces:**
- Produces: `validate_storyboard` 对合法/非法 `formula` 返回正确 `errors` / `warnings`
- Consumes: 现有 `resolve_kind`、`LEAK_RE`

- [ ] **Step 1: Write the failing tests**

在 `tests/test_make_video.py` 的转义/闸门区附近加入：

```python
def _rule_formula_scene(**kw):
    sc = {
        "kind": "rule",
        "layout_variant": "formula",
        "header": "夏普",
        "sub": "副",
        "narrate": "旁白",
        "body": "",
        "formula": {
            "num": "R<sub>p</sub>",
            "den": "σ<sub>p</sub>",
            "parts": [
                {"id": "num", "label": "分子", "text": "超额"},
                {"id": "den", "label": "分母", "text": "波动"},
            ],
        },
    }
    sc.update(kw)
    return sc


def test_formula_scene_accepts_num_den_parts():
    tpl = {"title": "T", "voice": "mimo_default", "scenes": [_rule_formula_scene()]}
    errs, warns = sg.validate_storyboard(tpl)
    assert not any("formula" in e or "body" in e for e in errs), errs


def test_formula_scene_requires_display_or_num_den():
    sc = _rule_formula_scene()
    sc["formula"] = {"parts": [{"id": "a", "label": "A", "text": "t"},
                               {"id": "b", "label": "B", "text": "t"}]}
    tpl = {"title": "T", "voice": "mimo_default", "scenes": [sc]}
    errs, _ = sg.validate_storyboard(tpl)
    assert any("formula" in e and ("display" in e or "num" in e or "den" in e) for e in errs)


def test_formula_scene_parts_length_and_unique_id():
    sc = _rule_formula_scene()
    sc["formula"]["parts"] = [{"id": "x", "label": "A", "text": "t"}]  # len 1
    errs, _ = sg.validate_storyboard({"title": "T", "voice": "mimo_default", "scenes": [sc]})
    assert any("parts" in e for e in errs)
    sc2 = _rule_formula_scene()
    sc2["formula"]["parts"] = [
        {"id": "x", "label": "A", "text": "t"},
        {"id": "x", "label": "B", "text": "t"},
    ]
    errs2, _ = sg.validate_storyboard({"title": "T", "voice": "mimo_default", "scenes": [sc2]})
    assert any("id" in e for e in errs2)


def test_formula_scene_body_nonempty_warns():
    sc = _rule_formula_scene(body="旧正文")
    _, warns = sg.validate_storyboard({"title": "T", "voice": "mimo_default", "scenes": [sc]})
    assert any("body" in w and "formula" in w for w in warns)


def test_formula_on_non_rule_warns():
    sc = {
        "kind": "example", "header": "h", "body": "**b**", "narrate": "n",
        "formula": {"display": "x"},
    }
    _, warns = sg.validate_storyboard({"title": "T", "voice": "mimo_default", "scenes": [sc]})
    assert any("formula" in w for w in warns)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `py -m pytest tests/test_make_video.py::test_formula_scene_accepts_num_den_parts tests/test_make_video.py::test_formula_scene_requires_display_or_num_den tests/test_make_video.py::test_formula_scene_parts_length_and_unique_id tests/test_make_video.py::test_formula_scene_body_nonempty_warns tests/test_make_video.py::test_formula_on_non_rule_warns -v`

Expected: FAIL（`body` 不能为空 和/或 尚无 formula 逻辑）

- [ ] **Step 3: Implement validation**

在 `validate_storyboard` 的 per-scene 循环中：

1. 先算 `kind` / `variant = sc.get("layout_variant")`
2. 若 `sc.get("formula") is not None`：
   - 非 rule 或 variant != `"formula"` → `warnings.append(...)`，可 `continue` 跳过结构校验
   - 否则调用新函数 `validate_formula_field(sc, prefix) -> (errors, warnings)`
3. 修改空字段检查：当 rule+formula 变体且 `formula` 为合法 object 时，`body` **不**因空而 error；若 `body` 非空则 warn

`validate_formula_field` 逻辑（放在 `validate_storyboard` 上方）：

```python
def validate_formula_field(sc, prefix):
    """返回 (errors, warnings)。仅在 rule+formula 变体调用。"""
    errors, warnings = [], []
    formula = sc.get("formula")
    if not isinstance(formula, dict):
        errors.append(f"{prefix}: formula 须为 object")
        return errors, warnings
    num = formula.get("num")
    den = formula.get("den")
    display = (formula.get("display") or "").strip()
    has_frac = bool((num or "").strip() and (den or "").strip())
    if not has_frac and not display:
        errors.append(
            f"{prefix}: formula 须提供 num+den，或非空 display"
        )
    body = (sc.get("body") or "").strip()
    if body:
        warnings.append(
            f"{prefix}: 已提供 formula，body 将被忽略（以 formula 为准）"
        )
    parts = formula.get("parts")
    if parts is None:
        return errors, warnings
    if not isinstance(parts, list) or not (2 <= len(parts) <= 4):
        errors.append(f"{prefix}: formula.parts 须为长度 2–4 的数组")
        return errors, warnings
    seen = set()
    for j, p in enumerate(parts):
        pp = f"{prefix}.formula.parts[{j}]"
        if not isinstance(p, dict):
            errors.append(f"{pp}: 须为 object")
            continue
        for f in ("id", "label", "text"):
            if not str(p.get(f) or "").strip():
                errors.append(f"{pp}: {f} 不能为空")
        pid = str(p.get("id") or "").strip()
        if pid:
            if pid in seen:
                errors.append(f"{pp}: id={pid!r} 重复")
            seen.add(pid)
    return errors, warnings
```

空字段循环改为：

```python
required = ["header", "narrate"]
kind_for_body = kind
variant = sc.get("layout_variant")
formula_ok = (
    kind_for_body == "rule"
    and variant == "formula"
    and isinstance(sc.get("formula"), dict)
)
if not formula_ok:
    required = ["header", "body", "narrate"]
for field in required:
    ...
```

（`formula_ok` 时 body 空不报错；非空 warn 放在 `validate_formula_field`。）

- [ ] **Step 4: Run tests to verify they pass**

Run: 同 Step 2 命令  
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add scripts/storyboard_gate.py tests/test_make_video.py
git commit -m "feat(gate): rule formula 变体校验 formula/num/den/parts"
```

---

### Task 2: 构建主式 / 分项 HTML + `render_html` 注入

**Files:**
- Modify: `scripts/storyboard_gate.py`（`render_html`、新 builder、`LAYOUT_VARIANT_SLOTS`、layout needs）
- Test: `tests/test_make_video.py`

**Interfaces:**
- Produces:
  - `build_formula_main_html(formula: dict, kind: str) -> str`
  - `build_formula_parts_html(parts: list | None, *, legacy_zh: str, badge: str) -> str`
  - `render_html` slots: `__FORMULA_MAIN__`, `__PARTS__`（formula layout）；旧路径兼容
- Consumes: `_escape`, `highlight_body`, `KIND_BADGE`

- [ ] **Step 1: Write the failing tests**

```python
def test_build_formula_main_html_fraction():
    html = sg.build_formula_main_html(
        {"num": "R<sub>p</sub>", "den": "σ<sub>p</sub>"}, "rule"
    )
    assert 'class="formula-frac"' in html
    assert 'class="formula-num"' in html
    assert 'class="formula-den"' in html
    assert "R<sub>p</sub>" in html
    assert "σ<sub>p</sub>" in html


def test_build_formula_main_html_display_fallback():
    html = sg.build_formula_main_html({"display": "R<sub>p</sub>/σ"}, "rule")
    assert 'class="formula"' in html
    assert "R<sub>p</sub>/σ" in html
    assert "formula-frac" not in html


def test_render_html_formula_injects_parts_and_data_id():
    sc = _rule_formula_scene()
    html = mv.render_html(sc, 1280, 720, mv.load_style("teaching"))
    assert "__FORMULA_MAIN__" not in html
    assert "__PARTS__" not in html
    assert 'data-part-id="num"' in html
    assert 'data-part-id="den"' in html
    assert "超额" in html


def test_render_html_legacy_formula_variant_uses_body():
    sc = {
        "kind": "rule", "layout_variant": "formula",
        "header": "H", "sub": "S", "body": "E = **mc**", "zh": "步骤说明",
        "narrate": "n",
    }
    html = mv.render_html(sc, 1280, 720, mv.load_style("teaching"))
    assert "mc" in html or "<span class=\"hl\">" in html
    assert "步骤说明" in html
```

- [ ] **Step 2: Run tests — expect FAIL**（函数未定义 / 槽未换）

Run: `py -m pytest tests/test_make_video.py::test_build_formula_main_html_fraction tests/test_make_video.py::test_build_formula_main_html_display_fallback tests/test_make_video.py::test_render_html_formula_injects_parts_and_data_id tests/test_make_video.py::test_render_html_legacy_formula_variant_uses_body -v`

- [ ] **Step 3: Implement builders + render_html**

```python
def build_formula_main_html(formula, kind):
    """主公式 HTML：优先 num+den 分式，否则 display 单行。"""
    num = (formula.get("num") or "").strip()
    den = (formula.get("den") or "").strip()
    if num and den:
        return (
            '<div class="formula-frac" data-formula-main="1">'
            f'<div class="formula-num">{highlight_body(num, kind)}</div>'
            '<div class="formula-bar" aria-hidden="true"></div>'
            f'<div class="formula-den">{highlight_body(den, kind)}</div>'
            "</div>"
        )
    display = formula.get("display") or ""
    return (
        f'<div class="formula" data-formula-main="1">'
        f"{highlight_body(display, kind)}</div>"
    )


def build_formula_parts_html(parts, *, legacy_zh="", badge=""):
    """分项 HTML；parts 为 None 时走旧双步（zh + badge）兼容。"""
    if parts is None:
        items = [
            {"id": "legacy1", "label": "1", "text": legacy_zh},
            {"id": "legacy2", "label": "2", "text": badge},
        ]
    else:
        items = parts
    chunks = ['<div class="breakdown">']
    for i, p in enumerate(items):
        pid = _escape(str(p.get("id") or f"p{i}"))
        label = _escape(str(p.get("label") or str(i + 1)))
        text = highlight_body(p.get("text") or "", "rule")
        chunks.append(
            f'<div class="step" data-part-id="{pid}">'
            f'<div class="step-num">{label}</div>'
            f'<div class="step-text part-text">{text}</div></div>'
        )
    chunks.append("</div>")
    return "".join(chunks)
```

在 `render_html` 中，构造 `slots` 前：

```python
formula = sc.get("formula") if isinstance(sc.get("formula"), dict) else None
use_formula = kind == "rule" and layout_variant == "formula"
if use_formula and formula is not None:
    formula_main = build_formula_main_html(formula, kind)
    parts_html = build_formula_parts_html(formula.get("parts"))
elif use_formula:
    formula_main = f'<div class="formula" data-formula-main="1">{body_html}</div>'
    parts_html = build_formula_parts_html(
        None, legacy_zh=str(zh), badge=KIND_BADGE.get(kind, "")
    )
else:
    formula_main = ""
    parts_html = ""
```

`slots` 增加：

```python
"__FORMULA_MAIN__": formula_main,
"__PARTS__": parts_html,
```

更新：

```python
LAYOUT_VARIANT_SLOTS = {
    ("rule", "side"): ["__ZH__"],
    ("rule", "formula"): ["__FORMULA_MAIN__", "__PARTS__"],
    ("example", "side"): ["__WRONG_BODY__"],
}
```

调整 `validate_layouts` 中 formula 变体的 `need`：在拼接后把 `__BODY__` 从 need 里去掉（formula 文件不再放 `__BODY__`）：

```python
need = _layout_needs(kind) + LAYOUT_VARIANT_SLOTS.get((kind, variant), [])
if (kind, variant) == ("rule", "formula"):
    need = [s for s in need if s != "__BODY__"]
```

同步改 `tests/test_make_video.py` 里若有断言 formula layout 必须含 `__BODY__` / `__ZH__` 的用例（如 `test_validate_layouts_checks_existing_variant_slots` 只测 side，通常不用改）。

- [ ] **Step 4: Run tests — expect PASS**（此时 layout 文件可能仍缺新槽 → `validate_layouts` 在 prepare 时失败）

若 `render_html` 测试因 layout 缺槽仍失败，先进入 Task 3 改 layout，再回到本步绿。

- [ ] **Step 5: Commit**（若 layout 未改导致无法绿，与 Task 3 合并一次 commit 亦可；优先分开）

```bash
git add scripts/storyboard_gate.py tests/test_make_video.py
git commit -m "feat(gate): 构建 formula 主式/分项 HTML 并注入槽位"
```

---

### Task 3: 重写 `layout-rule-formula.html`

**Files:**
- Modify: `templates/layout-rule-formula.html`
- Test: `tests/test_make_video.py`（`validate_layouts` + render 断言）

**Interfaces:**
- Consumes: `__FORMULA_MAIN__`, `__PARTS__`, 既有 style token
- Produces: 分式 CSS（`.formula-frac` / `.formula-num` / `.formula-bar` / `.formula-den`）、`.part-text`；保留 `.hl`/`.err`

- [ ] **Step 1: Write / adjust failing layout contract test**

```python
def test_formula_layout_has_formula_slots():
    raw = open("templates/layout-rule-formula.html", encoding="utf-8").read()
    assert "__FORMULA_MAIN__" in raw
    assert "__PARTS__" in raw
    assert "__BODY__" not in raw or raw.count("__BODY__") == 0
    errs = mv.validate_layouts()
    assert not any("layout-rule-formula.html" in e for e in errs), errs
```

- [ ] **Step 2: Run — expect FAIL**

- [ ] **Step 3: Replace layout content**

目标结构（CSS 可微调，但 class 名须与 builder / overflow 一致）：

- `.formula-card` 内仅 `__FORMULA_MAIN__`
- `__PARTS__` 已含 `.breakdown` 外层，layout 中直接放 `__PARTS__`（不要再包一层 breakdown）
- `.formula-frac`：flex column，居中；`.formula-bar`：height 3px，width 100%，max-width 420px，background `__ACCENT__`
- `.formula-num` / `.formula-den`：font-size `calc(__BODY_SIZE__px * 1.25)`，font-weight 700
- `.breakdown`：flex；3–4 项时 `flex-wrap: wrap`；`.step` 保持卡片感
- overflow 相关 class：`.formula`、`.formula-frac`、`.part-text` 已存在或由 builder 带上

完整文件可用下列骨架（保留 token，勿烘焙色值数字进文本节点）：

```html
<!DOCTYPE html><html><head><meta charset="utf-8"><style>
*{margin:0;padding:0;box-sizing:border-box}
body{width:__W__px;height:__H__px;background:linear-gradient(135deg,__BG__ 0%,__BG2__ 100%);font-family:__FONT__;color:__INK__;overflow:hidden}
.stage{position:relative;width:100%;height:100%;padding:36px 60px;display:flex;flex-direction:column;align-items:center;justify-content:flex-start;text-align:center}
.hd{display:flex;flex-direction:column;align-items:center;gap:10px;margin-bottom:6px}
.title{font-size:__TITLE_SIZE__px;font-weight:800;color:__INK__;letter-spacing:1px}
.badge{font-size:__BADGE_SIZE__px;color:__ACCENT__;border:1.5px solid __ACCENT__;border-radius:999px;padding:4px 16px;white-space:nowrap;opacity:.92}
.rule{width:56px;height:3px;background:__ACCENT__;border-radius:2px;margin:6px 0 2px}
.sub{font-size:__SUB_SIZE__px;color:__INK_SUB__;letter-spacing:.5px;max-width:920px;margin-bottom:12px}
.formula-card{width:100%;max-width:960px;background:__SURFACE__;border:1px solid __ACCENT__;border-radius:22px;padding:28px 48px;box-shadow:0 4px 20px rgba(0,0,0,0.22);display:flex;align-items:center;justify-content:center;margin-bottom:16px}
.formula{font-size:calc(__BODY_SIZE__px * 1.15);line-height:1.5;font-weight:700;text-align:center;letter-spacing:1px}
.formula-frac{display:flex;flex-direction:column;align-items:center;gap:8px;width:100%;max-width:720px}
.formula-num,.formula-den{font-size:calc(__BODY_SIZE__px * 1.25);line-height:1.35;font-weight:700;text-align:center}
.formula-bar{width:100%;max-width:420px;height:3px;background:__ACCENT__;border-radius:2px}
.breakdown{display:flex;flex-wrap:wrap;gap:20px;width:100%;max-width:960px;flex:1;min-height:0;justify-content:center}
.step{flex:1 1 200px;max-width:440px;background:__SURFACE__;border:1px solid __SURFACE_BORDER__;border-radius:18px;padding:16px 20px;box-shadow:0 2px 12px rgba(0,0,0,0.12);display:flex;flex-direction:column;align-items:center;justify-content:center;gap:8px}
.step-num{min-width:28px;height:28px;padding:0 8px;border-radius:999px;background:__ACCENT__;color:__BG__;font-size:14px;font-weight:800;display:flex;align-items:center;justify-content:center}
.step-text,.part-text{font-size:calc(__BODY_SIZE__px * 0.55);line-height:1.45;font-weight:500;text-align:center}
.hl{color:__ACCENT__;font-weight:800}
.err{color:__WRONG__;font-weight:800}
</style></head><body>
<div class="stage">
  <div class="hd"><div class="title">__HEADER__</div><div class="badge">__BADGE__</div></div>
  <div class="rule"></div>
  <div class="sub">__SUB__</div>
  <div class="formula-card">__FORMULA_MAIN__</div>
  __PARTS__
</div>
</body></html>
```

- [ ] **Step 4: Update overflow selectors**

在 `_OVERFLOW_SELECTORS_BY_KIND["rule"]` 增加 `".formula-frac"`, `".formula-num"`, `".formula-den"`, `".part-text"`（保留原 `.formula`）。

- [ ] **Step 5: Run tests**

Run:

```bash
py -m pytest tests/test_make_video.py::test_formula_layout_has_formula_slots tests/test_make_video.py::test_build_formula_main_html_fraction tests/test_make_video.py::test_render_html_formula_injects_parts_and_data_id tests/test_make_video.py::test_render_html_legacy_formula_variant_uses_body tests/test_make_video.py::test_validate_layouts_requires_think_slot -v
```

Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add templates/layout-rule-formula.html scripts/storyboard_gate.py tests/test_make_video.py
git commit -m "feat(layout): rule formula 页分式主式与 parts 槽位"
```

---

### Task 4: 文档同步

**Files:**
- Modify: `docs/json-schema.md`, `docs/formulas.md`
- Modify: `SKILL.md`（Context pointer 已有公式行则可在 formulas 节加「结构化」链）

- [ ] **Step 1: Update `docs/json-schema.md`**

在 `scenes[]` 表增加：

| formula | rule + layout_variant formula | 对象：`display` / `num` / `den` / `parts[]`；见 formulas.md |

在排版变体 `formula` 行注明：推荐 `formula` 对象；仅 `body` 仍兼容。

- [ ] **Step 2: Update `docs/formulas.md`**

在白名单节后增加「结构化 formula（推荐）」：复制 spec 示例；说明旧 `body` 兼容与 `body`+`formula` 并存时的 warn。

- [ ] **Step 3: Commit**

```bash
git add docs/json-schema.md docs/formulas.md SKILL.md
git commit -m "docs: 记录 rule formula 结构化字段"
```

---

### Task 5: 回归与手工验收

**Files:** 无新文件（或可选临时分镜，勿强制 tracked）

- [ ] **Step 1: 跑相关与闸门回归**

```bash
py -m pytest tests/test_make_video.py -q --tb=line
```

Expected: 全绿（或仅跳过浏览器 fixture）

- [ ] **Step 2: 手工 preview（有浏览器时）**

构造临时 JSON（可放 `.scratch/`，不提交）含 Task 1 示例 scene，执行：

```bash
py scripts/make_video.py .scratch/formula_demo.json --preview
```

Expected: exit 0；`_build/runs/.../preview/` 有截图；主式为分式、两项拆解可见。

- [ ] **Step 3: 旧路径冒烟**

用仅 `body` 的 `layout_variant: formula` 页跑 `--preview`，确认仍出片且无回归 error。

- [ ] **Step 4: 若有修复则 commit；否则记录验证于 commit message 空操作不需要**

```bash
git status
```

---

## Out of scope（本 plan 不做）

- 第二期：按 `parts[].id` 的 motion / 拟物（另写 plan，依据 spec §4）
- KaTeX、其它 kind、#27、默认 1080p

## Spec coverage self-check

| Spec 项 | Task |
| --- | --- |
| formula 字段与校验 | Task 1 |
| body 可空 + warn | Task 1 |
| 主式 num/den 或 display | Task 2–3 |
| parts 2–4 + data-part-id | Task 2–3 |
| 旧分镜兼容 | Task 2 legacy 路径 + Task 5 |
| layout / overflow | Task 3 |
| 文档 | Task 4 |
| 二期动效 | 明确排除 |

## Placeholder scan

无 TBD / 「类似 Task N」占位；测试与实现代码已内联。
