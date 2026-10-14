"""文档与实现的一致性断言：同一规则只写一遍，写歪了就红。

项目已有同族断言（test_gate_hold_floor_message_matches_docs：代码里的门槛文案必须与
文档字面一致）。这里把同一条纪律补到 run_key 组成与「manifest 缺失」规则上——这两处
此前各漂移过一次：run_key 公式漏了 templates/ 内容，而文档仍承诺一个已被删除、
且被测试明令禁止的回退。
"""

import json
import os
import re
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "scripts"))

import run_artifacts as ra  # noqa: E402
import storyboard_gate as sg  # noqa: E402


def _read(rel):
    with open(os.path.join(ROOT, rel), encoding="utf-8") as f:
        return f.read()


def test_audio_doc_run_key_formula_covers_every_real_input():
    """文档写出的 run_key 组成必须覆盖实现真正吃的每一项输入。

    实现侧逐项验证「改这一项 → key 变」，文档侧逐项验证「这一项被写出来」，
    两侧用同一份清单，漏一项即失败。
    """
    with tempfile.TemporaryDirectory(prefix="doc_rk_") as d:
        root = os.path.join(d, "repo")
        tdir = os.path.join(root, "templates")
        os.makedirs(tdir)
        tpl_file = os.path.join(tdir, "layout-rule.html")
        with open(tpl_file, "w", encoding="utf-8") as f:
            f.write("<div>__BODY__</div>")
        sb = os.path.join(d, "lesson.json")
        with open(sb, "w", encoding="utf-8") as f:
            json.dump({"scenes": []}, f)

        # 1 分镜字节
        k0 = ra.run_key(sb, "teaching", True, root)
        with open(sb, "w", encoding="utf-8") as f:
            json.dump({"scenes": [{"kind": "rule"}]}, f)
        k1 = ra.run_key(sb, "teaching", True, root)
        assert k1 != k0, "分镜字节未参与 run_key"
        # 2 style
        assert ra.run_key(sb, "classroom", True, root) != k1, "style 未参与 run_key"
        # 3 motion 开关
        assert ra.run_key(sb, "teaching", False, root) != k1, "motion 开关未参与 run_key"
        # 4 templates/ 内容
        with open(tpl_file, "w", encoding="utf-8") as f:
            f.write('<div class="x">__BODY__</div>')
        assert ra.run_key(sb, "teaching", True, root) != k1, "模板内容未参与 run_key"

    line = next(
        ln for ln in _read("docs/audio.md").splitlines() if "run_key = sha256" in ln
    )
    for token in ("分镜文件字节", "style", "motion", "templates/"):
        assert token in line, f"docs/audio.md 的 run_key 公式漏了 {token}：{line}"


def test_audio_doc_and_verifier_agree_there_is_no_manifest_fallback():
    """manifest 缺失只有一个口径：检查 4 失败，不猜文件名。

    文档一度承诺「回退旧版共享音轨」，而 worker_verify 与
    test_verify_without_manifest_fails_without_guessing 都禁止回退。
    """
    doc = _read("docs/audio.md")
    assert "manifest 缺失即检查 4 失败" in doc, "文档没写清 manifest 缺失时的行为"
    assert not re.search(r"manifest\s*缺失时回退", doc), "文档仍在承诺已删除的回退"

    verifier = _read("scripts/worker_verify.py")
    assert "不回退到共享 raw 目录" in verifier, "verify 的口径变了，文档需同步"


def test_audio_doc_agrees_on_where_artifacts_live():
    """产物归属：raw 共享、加工音轨与预览归本次 run。"""
    doc = _read("docs/audio.md")
    for token in ("_build/runs/", "raw 可共享", "加工音轨归"):
        assert token in doc, f"docs/audio.md 的产物归属描述漏了 {token}"


def test_skip_preview_contract_is_documented_where_it_is_used():
    """--skip-preview 的准入条件写在 SKILL.md 与 json-schema.md，不只活在 --help 里。"""
    for rel in ("SKILL.md", "docs/json-schema.md"):
        text = _read(rel)
        assert "overflow.json" in text, f"{rel} 未说明 --skip-preview 读什么"
        assert "指纹" in text, f"{rel} 未说明报告须属于本次分镜"


def test_doc_agrees_with_gate_on_unknown_layout_variant():
    """未知 layout_variant 是闸门报错，不是「自动回退默认」。

    闸门自 1b15de3 起对未知变体硬报错（原先静默回退），但 json-schema 与
    prepare_storyboard 的 docstring 仍承诺回退——写分镜的人会按文档预期被放过。
    """
    doc = _read("docs/json-schema.md")
    assert "变体文件不存在时自动回退默认" not in doc, "文档仍在承诺已删除的回退"
    assert "回退默认 layout" not in doc, "字段表仍在承诺未知变体回退默认"

    errors, _ = sg.validate_storyboard(
        {
            "title": "T",
            "scenes": [
                {"kind": "rule", "layout_variant": "nope", "header": "H",
                 "body": "B", "narrate": "N"}
            ],
        }
    )
    assert any("未知 layout_variant" in e for e in errors), (
        f"闸门不再对未知 layout_variant 报错：{errors}"
    )
    assert "未知/缺失变体回退默认" not in _read("scripts/storyboard_gate.py"), (
        "prepare_storyboard 的 docstring 仍承诺回退默认"
    )


def test_doc_states_the_numeric_caps_the_gate_enforces():
    """json-schema 必须写出闸门实际拦的数值上限：fps / 宽高 / hold。"""
    doc = _read("docs/json-schema.md")

    def _errors(**top):
        """fps 与 hold 的上限由 validate_storyboard 拦。"""
        tpl = {"title": "T", "scenes": []}
        tpl.update(top)
        return sg.validate_storyboard(tpl)[0]

    assert any("fps=121 超过上限 120" in e for e in _errors(fps=121))

    def _prepared(**top):
        """宽高上限由 prepare_storyboard 拦。"""
        tpl = {"title": "T", "scenes": []}
        tpl.update(top)
        return sg.prepare_storyboard(tpl)["errors"]

    assert any("width=3841 超过上限 3840" in e for e in _prepared(width=3841))
    assert any("height=3841 超过上限 3840" in e for e in _prepared(height=3841))

    scene = {"kind": "rule", "header": "H", "body": "B", "narrate": "N"}
    assert any("hold=601 超过上限 600" in e for e in sg.validate_storyboard(
        {"title": "T", "scenes": [dict(scene, hold=601)]})[0])

    fps_row = next(ln for ln in doc.splitlines() if ln.startswith("| fps"))
    assert "120" in fps_row, f"fps 行没写上限：{fps_row}"
    wh_row = next(ln for ln in doc.splitlines() if ln.startswith("| width / height"))
    assert "3840" in wh_row, f"宽高行没写上限：{wh_row}"
    hold_row = next(ln for ln in doc.splitlines() if ln.startswith("| hold |"))
    assert "600" in hold_row and "120" in hold_row, f"hold 行没写上限与长停顿告警：{hold_row}"


def test_voice_warning_does_not_misname_the_active_engine():
    """音色校验按本次 provider 走，不得拿 xiaomi 清单拦别家。

    闸门曾用 xiaomi 的音色白名单校验所有引擎：provider=minimax 时，
    MiniMax 官方 voice_id 会被误报，而用户无从判断该改音色还是该换引擎。
    """
    _, warnings = sg.validate_storyboard(
        {"title": "T", "tts_provider": "minimax",
         "voice": "Chinese (Mandarin)_Gentle_Senior", "scenes": []}
    )
    assert not [w for w in warnings if "voice=" in w], (
        f"MiniMax 官方 voice_id 被误报：{warnings}"
    )

    _, qwen_warnings = sg.validate_storyboard(
        {"title": "T", "tts_provider": "qwen", "voice": "longanlingxin", "scenes": []}
    )
    assert not [w for w in qwen_warnings if "voice=" in w], (
        f"Qwen 官方 voice_id 被误报：{qwen_warnings}"
    )

    _, xiaomi_warnings = sg.validate_storyboard(
        {"title": "T", "tts_provider": "xiaomi", "voice": "mimo_default", "scenes": []}
    )
    assert not [w for w in xiaomi_warnings if "voice=" in w], (
        f"xiaomi 自己的音色被误报：{xiaomi_warnings}"
    )

    _, unknown = sg.validate_storyboard(
        {"title": "T", "tts_provider": "minimax", "voice": "不存在", "scenes": []}
    )
    msg = next(w for w in unknown if "不存在" in w)
    assert "minimax" in msg, f"告警未说明该用哪家的音色表：{msg}"


def test_doc_offers_a_choice_of_tts_engines():
    """用户必须能自己选引擎：SKILL.md 与 json-schema 都要写出三家与对应 Key。"""
    skill = _read("SKILL.md")
    for token in ("minimax", "xiaomi", "qwen",
                  "MINIMAX_API_KEY", "MIMO_API_KEY", "DASHSCOPE_API_KEY"):
        assert token in skill, f"SKILL.md 未列出 {token}"

    schema = _read("docs/json-schema.md")
    tts_row = next(ln for ln in schema.splitlines() if ln.startswith("| tts_provider"))
    for token in ("minimax", "xiaomi", "qwen", "--tts-provider"):
        assert token in tts_row, f"tts_provider 行没写出 {token}：{tts_row}"