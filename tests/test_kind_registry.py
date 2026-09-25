"""kind 注册表测试：一个 kind 的全部事实只有一处，派生视图不得漏项。

这些断言不需要浏览器、ffmpeg 或 TTS——它们检查的是「加一个 kind 时会不会漏填」，
也就是注册表存在的理由。
"""

import os
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "scripts"))

import storyboard_gate as sg  # noqa: E402

KINDS = sorted(sg.KIND_REGISTRY)

# 注册表字段 → 由它派生的模块级视图。派生视图必须与注册表同键集，
# 否则就是「改了一张表漏了另一张」，正是本注册表要消灭的失效模式。
DERIVED = {
    "layout": sg.LAYOUT_FILES,
    "badge": sg.KIND_BADGE,
    "motion": sg.KIND_MOTION,
    "arc_phase": sg._ARC_PHASE,
    "overflow_selectors": sg._OVERFLOW_SELECTORS_BY_KIND,
}


def test_every_derived_view_covers_every_kind():
    for field, view in DERIVED.items():
        assert set(view) == set(KINDS), f"{field} 派生视图与注册表键集不一致"


def test_registry_is_the_only_source_of_kinds():
    assert KINDS == sorted(sg.LAYOUT_FILES)
    assert KINDS == sorted(sg._OVERFLOW_SELECTORS_BY_KIND)


def test_roles_round_trip():
    assert set(sg.ROLE_TO_KIND) == {sg.KIND_REGISTRY[k].role for k in KINDS}
    for kind in KINDS:
        assert sg.KIND_TO_ROLE[kind] == sg.KIND_REGISTRY[kind].role
        assert sg.ROLE_TO_KIND[sg.KIND_REGISTRY[kind].role] == kind


def test_every_registered_layout_file_exists():
    """注册了就得到模板：漏文件原先要到渲染/预览时才炸。"""
    for kind in KINDS:
        spec = sg.KIND_REGISTRY[kind]
        assert os.path.isfile(os.path.join(sg.TEMPLATE_DIR, spec.layout)), (
            f"{kind} 的 layout {spec.layout} 不存在"
        )
        for variant, fn in spec.variants.items():
            assert os.path.isfile(os.path.join(sg.TEMPLATE_DIR, fn)), (
                f"{kind}/{variant} 的 layout {fn} 不存在"
            )


def test_variant_slots_declare_their_variant():
    for kind in KINDS:
        spec = sg.KIND_REGISTRY[kind]
        assert set(spec.variant_slots) <= set(spec.variants), (
            f"{kind} 的 variant_slots 声明了未注册的变体"
        )
        for variant, slots in spec.variant_slots.items():
            assert slots, f"{kind}/{variant} 的额外槽位为空"


def test_needs_are_non_empty_and_unique():
    for kind in KINDS:
        needs = sg.KIND_REGISTRY[kind].needs
        assert needs, f"{kind} 没有槽位要求"
        assert len(needs) == len(set(needs)), f"{kind} 的槽位要求有重复"
        assert all(n.startswith("__") and n.endswith("__") for n in needs), needs
        # 与 validate_layouts 实际使用的一致（派生自同一记录）
        assert sg._layout_needs(kind) == needs


def test_overflow_selectors_unique_and_not_exempt():
    for kind in KINDS:
        sels = sg._OVERFLOW_SELECTORS_BY_KIND[kind]
        assert sels, f"{kind} 没有溢出选择器"
        assert len(sels) == len(set(sels)), f"{kind} 的溢出选择器有重复"
        # 装饰性容器只能被豁免，不能被当成文字槽之外的重复项混进来
        assert not (set(sels) & sg._CLIP_EXEMPT_SELECTORS) or kind == "diagram"


def test_unknown_kind_fails_loudly():
    """未知 kind 直接报错，而不是套一份默认槽位表悄悄放行。"""
    with pytest.raises(KeyError):
        sg._layout_needs("timeline")
    with pytest.raises(KeyError):
        sg.KIND_REGISTRY["timeline"]


def test_arc_phases_span_the_documented_arc():
    phases = {k: sg.KIND_REGISTRY[k].arc_phase for k in KINDS}
    assert phases["title"] == min(phases.values())
    assert phases["summary"] == max(phases.values())
    assert sorted(set(phases.values())) == list(range(len(set(phases.values()))))


def test_only_title_has_an_empty_badge():
    """空 badge 是 title 的刻意选择；别的 kind 漏填 badge 就是缺陷。"""
    empty = [k for k in KINDS if not sg.KIND_REGISTRY[k].badge]
    assert empty == ["title"], empty


def test_every_kind_declares_a_motion_in_the_allowed_set():
    for kind in KINDS:
        assert sg.KIND_REGISTRY[kind].motion in sg.MOTIONS, kind