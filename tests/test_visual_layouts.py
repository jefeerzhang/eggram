"""Generic variants: gate, escape, deterministic reveal and real browser overflow.

Synthetic scenes only; no existing lesson rewrite, TTS or video generation.
"""
import json
import os
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "scripts"))

import storyboard_gate as sg  # noqa: E402
import visual_layouts as vl  # noqa: E402


def scene(variant):
    visuals = {
        "structure": {"label": "能力组成", "items": [
            {"label": "规则", "text": "约束行为"},
            {"label": "工具", "text": "执行**动作**"},
            {"label": "记忆", "text": "保留经验"},
        ]},
        "steps": {"items": [
            {"label": "查看时段", "text": "周五 19:00", "result": "时段**空闲**"},
            {"label": "创建日程", "text": "会议：项目讨论", "result": "日程**创建成功**"},
        ]},
        "compare": {"items": [
            {"wrong": "规则**自己执行动作**", "right": "规则约束，**工具执行**", "reason": "规范与执行不是一回事。"},
            {"wrong": "记忆**等于知识库**", "right": "记忆保存**使用经验**", "reason": "用途不同。"},
        ]},
    }
    return {"kind": vl.VISUAL_KINDS[variant], "layout_variant": variant,
            "header": "合适的画面解释知识", "body": "不同对象各有分工。",
            "narrate": "按顺序说明对象之间的关系。", "visual": visuals[variant]}


def storyboard():
    return {"title": "视觉测试", "voice": "mimo_default", "scenes": [
        {"kind": "title", "header": "开场", "body": "测试", "narrate": "测试"},
        scene("structure"), scene("steps"), scene("compare"),
        {"kind": "practice", "header": "判断", "body": "**正确吗**", "narrate": "这句话正确吗", "hold": 5},
        {"kind": "answer", "header": "解释", "body": "**正确**", "narrate": "说明理由"},
        {"kind": "summary", "header": "总结", "body": "分工", "narrate": "记住分工"},
    ]}


def cfg(style="teaching", W=1280, H=720):
    return sg.RenderConfig(W=W, H=H, style=sg.load_style(style), fps=30,
                           motion_enabled=True, style_name=style)


@pytest.mark.parametrize("variant", vl.VISUAL_KINDS)
def test_registered_variants_and_documented_slots(variant):
    kind = vl.VISUAL_KINDS[variant]
    assert sg.resolve_layout_file(kind, variant) == "layout-visual.html"
    assert sg.LAYOUT_VARIANT_SLOTS[kind, variant] == ["__VISUAL__"]
    with open(os.path.join(ROOT, "docs", "json-schema.md"), encoding="utf-8") as f:
        schema = f.read()
    assert f'"{variant}"' in schema
    assert not sg.validate_layouts()


@pytest.mark.parametrize("style", ["teaching", "classroom", "explainer"])
def test_complete_arc_passes_gate_and_renders_all_variants(style):
    result = sg.prepare_storyboard(storyboard(), style_name=style)
    assert result["errors"] == []
    for entry in result["scenes"][1:4]:
        assert f'visual-{entry["variant"]}' in entry["html"]
        assert not sg.validate_rendered_html(entry["html"], entry["i"])
    assert 'class="err"' in result["scenes"][3]["html"]
    assert 'class="hl"' in result["scenes"][3]["html"]


@pytest.mark.parametrize("variant", vl.VISUAL_KINDS)
@pytest.mark.parametrize("bad", [None, "text", {}, {"items": []}, {"items": ["oops"]}, {"items": [{"label": 1}]}])
def test_bad_visual_is_blocked(variant, bad):
    sc = scene(variant)
    sc["visual"] = bad
    assert vl.validate_visual(sc, sc["kind"], "scenes[0]")
    with pytest.raises(ValueError):
        sg.render_html(sc, cfg())


@pytest.mark.parametrize("variant", vl.VISUAL_KINDS)
def test_unknown_fields_excess_items_empty_values_and_long_text(variant):
    sc = scene(variant)
    sc["visual"]["style"] = "red"
    assert any("未知字段" in x for x in vl.validate_visual(sc, sc["kind"], "scene"))
    sc = scene(variant)
    sc["visual"]["items"] *= 5
    assert vl.validate_visual(sc, sc["kind"], "scene")
    for field in vl._FIELDS[variant]:
        for bad in ("", "   ", False, "字" * 101):
            sc = scene(variant)
            sc["visual"]["items"][0][field] = bad
            assert vl.validate_visual(sc, sc["kind"], "scene")
    sc = scene(variant)
    sc["visual"]["items"][0]["delay"] = 2
    assert vl.validate_visual(sc, sc["kind"], "scene")


def test_visual_cannot_be_silently_ignored_on_other_layout():
    sc = scene("steps")
    sc.pop("layout_variant")
    assert vl.validate_visual(sc, sc["kind"], "scene")
    sc["layout_variant"] = "structure"
    assert vl.validate_visual(sc, sc["kind"], "scene")


def test_compare_requires_error_highlight_but_not_legacy_body_highlight():
    sb = storyboard()
    assert not sg.validate_storyboard(sb)[0]
    sb["scenes"][3]["visual"]["items"][0]["wrong"] = "没有标出错误"
    assert any("wrong" in e and "**" in e for e in sg.validate_storyboard(sb)[0])


@pytest.mark.parametrize("variant", vl.VISUAL_KINDS)
def test_visual_text_uses_existing_escape_contract(variant):
    sc = scene(variant)
    field = "wrong" if variant == "compare" else "text"
    sc["visual"]["items"][0][field] = '<script>alert(1)</script> **重点**<br>x<sup>2</sup>'
    html = sg.render_html(sc, cfg())
    assert '<script>' not in html
    assert '&lt;script&gt;' in html
    assert '<br>x<sup>2</sup>' in html
    assert '重点</span>' in html


@pytest.mark.parametrize("variant,field,selector", [
    ("structure", "root", ".visual-root"),
    ("structure", "label", ".visual-label"),
    ("steps", "label", ".visual-action"),
    ("compare", "reason", ".visual-reason"),
])
@pytest.mark.parametrize("literal", ["A<br>B<sup>2</sup>__X__", r"<rad>x</rad>\n"])
def test_browser_visual_labels_and_reasons_remain_literal(browser, variant, field, selector, literal):
    sc = scene(variant)
    if field == "root":
        sc["visual"]["label"] = literal
    else:
        sc["visual"]["items"][0][field] = literal
    assert not vl.validate_visual(sc, sc["kind"], "scene")
    html = sg.render_html(sc, cfg())
    assert not sg.validate_rendered_html(html, 0)
    page = browser.new_page(viewport={"width": 1280, "height": 720})
    try:
        page.set_content(html)
        element = page.locator(selector).first
        expected = "1" + literal if variant == "steps" else literal
        assert element.text_content() == expected
        assert element.locator("br, sup").count() == 0
    finally:
        page.close()


def test_reveal_clock_is_cumulative_seek_safe_and_frozen_during_hold():
    assert vl.visual_reveal_levels(3, 0, 6) == [0, 0, 0]
    assert vl.visual_reveal_levels(3, 1, 6) == [1, 0, 0]
    assert vl.visual_reveal_levels(3, 3, 6) == [1, 1, 0]
    assert vl.visual_reveal_levels(3, 5, 6) == [1, 1, 1]
    assert vl.visual_reveal_levels(3, 100, 6) == [1, 1, 1]
    assert vl.visual_reveal_levels(3, -1, 6) == [0, 0, 0]
    assert vl.visual_reveal_levels(3, 1, 0) == [1, 1, 1]
    assert vl.visual_reveal_levels(0, 1, 6) == []


@pytest.mark.parametrize("style", ["teaching", "classroom", "explainer"])
@pytest.mark.parametrize("variant", vl.VISUAL_KINDS)
def test_browser_complete_and_motion_states_fit(browser, style, variant):
    page = browser.new_page(viewport={"width": 1280, "height": 720})
    try:
        sc = scene(variant)
        page.set_content(sg.render_html(sc, cfg(style)))
        for elapsed in [None, 0, 1, 3, 6, 20, 0]:
            if elapsed is None:
                vl.apply_visual_state(page, sc)
            else:
                vl.apply_visual_state(page, sc, elapsed, 6)
            sg.apply_motion_css_vars(page, sg.motion_vars(sg.resolve_motion(sc), elapsed or 0, 6))
            assert not sg.preview_overflow(page, 1280, 720, sc["kind"])
            levels = page.locator('[data-visual-index]').evaluate_all(
                "els => els.map(el => Number(el.style.getPropertyValue('--v-on')))"
            )
            expected = [1] * len(sc["visual"]["items"]) if elapsed is None else vl.visual_reveal_levels(len(sc["visual"]["items"]), elapsed, 6)
            assert levels == expected
        # Static mode explicitly restores every result after seeking to start.
        vl.apply_visual_state(page, sc)
        assert page.locator('[data-visual-index]').evaluate_all(
            "els => els.every(el => el.style.getPropertyValue('--v-on') === '1')"
        )
        if variant == "compare":
            vl.apply_visual_state(page, sc, 0, 6)
            assert page.locator('.visual-reveal').first.evaluate("el => getComputedStyle(el).opacity") == '0'
            assert page.locator('.visual-wrong').first.is_visible()
    finally:
        page.close()


@pytest.mark.parametrize("variant", vl.VISUAL_KINDS)
def test_browser_catches_visual_overflow(browser, variant):
    page = browser.new_page(viewport={"width": 640, "height": 120})
    try:
        sc = scene(variant)
        page.set_content(sg.render_html(sc, cfg(W=640, H=120)))
        findings = sg.preview_overflow(page, 640, 120, sc["kind"])
        assert any(f["sel"].startswith('.visual') for f in findings), findings
    finally:
        page.close()


def test_existing_lessons_still_pass_gate():
    for name in os.listdir(os.path.join(ROOT, "examples")):
        if name.endswith('.json'):
            with open(os.path.join(ROOT, "examples", name), encoding="utf-8") as f:
                sb = json.load(f)
            # Old example fixtures already have warning/arc deviations. New visual rules must add none.
            errors, _ = sg.validate_storyboard(sb)
            assert not any('visual' in e for e in errors), (name, errors)
