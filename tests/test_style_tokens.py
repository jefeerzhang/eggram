"""皮肤 token 词表测试：必填 token 只声明一次，缺失在加载时就报错。

加一个皮肤（SKILL.md 的既定流程）原先有两种失败方式：palette 缺 key 静默变成空
字符串——屏幕上就是没颜色；typography 缺 key 直接 KeyError。这里钉住「两种都报」。
"""

import copy
import json
import os
import sys
import tempfile

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "scripts"))

import storyboard_gate as sg  # noqa: E402

SAMPLE = os.path.join(ROOT, "examples", "now_progressing.json")
SKINS = sorted(
    f for f in os.listdir(os.path.join(ROOT, "templates")) if f.startswith("style-")
)


def _shipped(style_name="teaching"):
    with open(
        os.path.join(ROOT, "templates", f"style-{style_name}.json"), encoding="utf-8"
    ) as f:
        return json.load(f)


def test_every_shipped_skin_declares_the_required_vocabulary():
    assert SKINS, "至少要有一套皮肤"
    for name in SKINS:
        with open(os.path.join(ROOT, "templates", name), encoding="utf-8") as f:
            style = json.load(f)
        assert sg.validate_style(style, name) == []


def test_token_map_covers_every_required_key():
    """必填 token 都要真的出现在 style_token_map 的输出里。

    映射不是机械大写：bg_grad2 → __BG2__、family → __FONT__。这张表同时钉住
    「必填表里的每个 key 都有 token」，多一个少一个都会红。
    """
    expected = {
        "bg": "__BG__",
        "bg_grad2": "__BG2__",
        "surface": "__SURFACE__",
        "surface_border": "__SURFACE_BORDER__",
        "ink": "__INK__",
        "ink_sub": "__INK_SUB__",
        "accent": "__ACCENT__",
        "correct": "__CORRECT__",
        "wrong": "__WRONG__",
        "family": "__FONT__",
        "title_size": "__TITLE_SIZE__",
        "body_size": "__BODY_SIZE__",
        "sub_size": "__SUB_SIZE__",
        "badge_size": "__BADGE_SIZE__",
    }
    required = set(
        sg.STYLE_REQUIRED_PALETTE_KEYS + sg.STYLE_REQUIRED_TYPOGRAPHY_KEYS
    )
    assert set(expected) == required, "必填表变了，token 映射表要同步"

    tokens = sg.style_token_map(_shipped())
    for style_key, token in expected.items():
        assert token in tokens, f"{style_key} 没有对应 token"
        assert tokens[token], f"{token} 解析为空"


def test_missing_palette_key_is_reported_not_silently_blank():
    """原先这里会静默给出空字符串——空白颜色是渲染出来才发现的缺陷。"""
    style = _shipped()
    del style["palette"]["correct"]
    errors = sg.validate_style(style, "s.json")
    assert any("palette 缺 token" in e and "correct" in e for e in errors)


def test_missing_typography_key_is_reported_too():
    """typography 原先直接 KeyError；现在与 palette 走同一条报错路径。"""
    style = _shipped()
    del style["typography"]["title_size"]
    errors = sg.validate_style(style, "s.json")
    assert any("typography 缺 token" in e and "title_size" in e for e in errors)


def test_palette_value_must_be_a_usable_colour():
    """key 在但值不可用（数字、空串）一样是空白颜色，必须拦。"""
    for bad in (123, "", "   ", None):
        style = _shipped()
        style["palette"]["accent"] = bad
        errors = sg.validate_style(style, "s.json")
        assert any("palette.accent" in e for e in errors), bad


def test_palette_accepts_the_hex_object_form():
    style = _shipped()
    style["palette"]["accent"] = {"hex": "#123456"}
    assert sg.validate_style(style, "s.json") == []


def test_missing_sections_are_reported():
    assert any("palette 段" in e for e in sg.validate_style({}, "s.json"))
    assert any("typography 段" in e for e in sg.validate_style({}, "s.json"))


def test_charts_required_tokens_are_declared_by_the_style_vocabulary():
    """charts.py 硬索引三个 token，那个依赖现在由必填表声明。"""
    src = open(os.path.join(ROOT, "scripts", "charts.py"), encoding="utf-8").read()
    for token in ('colors["__ACCENT__"]', 'colors["__INK_SUB__"]', 'colors["__SURFACE__"]'):
        assert token in src, f"charts.py 的 token 用法变了：{token}"
    tokens = sg.style_token_map(_shipped())
    for token in ("__ACCENT__", "__INK_SUB__", "__SURFACE__"):
        assert tokens[token], f"{token} 解析为空，charts 会拿到空颜色"


def test_load_style_rejects_a_skin_with_a_missing_token(monkeypatch):
    """加载即受检：坏皮肤在 load_style 就报错，不留到渲染时。"""
    with tempfile.TemporaryDirectory(prefix="skin_") as d:
        monkeypatch.setattr(sg, "TEMPLATE_DIR", d)
        bad = copy.deepcopy(_shipped())
        del bad["palette"]["correct"]
        with open(os.path.join(d, "style-broken.json"), "w", encoding="utf-8") as f:
            json.dump(bad, f, ensure_ascii=False)
        with pytest.raises(ValueError) as e:
            sg.load_style("broken")
        assert "correct" in str(e.value)


def test_prepare_storyboard_turns_a_bad_skin_into_a_gate_error(monkeypatch):
    """坏皮肤走闸门错误通道（CLI 打印 VALIDATION FAILED 并 exit 2），不是 traceback。"""
    with tempfile.TemporaryDirectory(prefix="skin_") as d:
        monkeypatch.setattr(sg, "TEMPLATE_DIR", d)
        bad = copy.deepcopy(_shipped())
        del bad["typography"]["body_size"]
        with open(os.path.join(d, "style-broken.json"), "w", encoding="utf-8") as f:
            json.dump(bad, f, ensure_ascii=False)
        with open(SAMPLE, encoding="utf-8") as f:
            tpl = json.load(f)
        tpl["style"] = "broken"
        prep = sg.prepare_storyboard(tpl)
        assert prep["errors"], "坏皮肤必须报成闸门错误"
        assert any("body_size" in e for e in prep["errors"])