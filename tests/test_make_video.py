"""make_video.py 的 8 张 P2 缺陷票回归测试。

纯函数部分不依赖浏览器/TTS；浏览器相关用 playwright（找不到浏览器时跳过）。
运行：python -m pytest tests/test_make_video.py -q
"""

import json
import os
import re
import shutil
import struct
import subprocess
import sys
import tempfile
from concurrent.futures import ThreadPoolExecutor

import numpy as np
import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "scripts"))

import make_video as mv  # noqa: E402
import storyboard_gate as sg  # noqa: E402
import toolchain as tc  # noqa: E402

SAMPLE = os.path.join(ROOT, "examples", "now_progressing.json")


def load_sample():
    with open(SAMPLE, encoding="utf-8") as f:
        return json.load(f)


def _cfg(style="teaching", W=1280, H=720, motion=True, fps=30):
    """渲染配置：一处构造，测试点不再各自 load_style + 拼 1280/720。

    style 收名字或已加载的 style 对象；皮肤文件只在这里读一次。
    motion 默认 True，与 render_html 原先的默认值一致——需要关掉的点显式传 False。
    """
    return sg.RenderConfig(
        W=W,
        H=H,
        style=style if isinstance(style, dict) else sg.load_style(style),
        fps=fps,
        motion_enabled=motion,
        style_name=style if isinstance(style, str) else "teaching",
    )


def _minimal_layout(kind):
    """构造能过 validate_layouts 必要槽位检查的极简 layout（仅用于测试）。"""
    slots = ["__HEADER__", "__BG__", "__ACCENT__", "__INK__"]
    if kind == "title":
        pass
    elif kind == "summary":
        slots = ["__BODY__", "__SUB__", "__BG__", "__ACCENT__", "__INK__"]
    else:
        slots += ["__BODY__", "__SUB__", "__BADGE__"]
        if kind in ("example", "mistake"):
            slots += ["__ZH__"]
    return " ".join(slots)


def wav_bytes(pcm, rate=24000, channels=1, sampwidth=2, extra_list=False):
    """构造 WAV 字节；extra_list 时在 data 前插入一个 LIST chunk，验证容器字节不被当声音。"""
    data = np.asarray(pcm, dtype=np.int16).tobytes()
    byte_rate = rate * channels * sampwidth
    block_align = channels * sampwidth
    bits = sampwidth * 8
    fmt = struct.pack(
        "<4sIHHIIHH", b"fmt ", 16, 1, channels, rate, byte_rate, block_align, bits
    )
    extra = b"LIST" + struct.pack("<I", 4) + b"INFO" if extra_list else b""
    data_chunk = b"data" + struct.pack("<I", len(data)) + data
    body = fmt + extra + data_chunk
    return b"RIFF" + struct.pack("<I", 4 + len(body)) + b"WAVE" + body


# ---- 01 教学文本转义 ----


def test_escape_sub_sup_whitelist_and_literal_guards():
    """公式白名单透传；R_p 仍转实体；任意标签与占位符字面不被误还原。"""
    assert sg._escape("R<sub>p</sub>") == "R<sub>p</sub>"
    assert sg._escape("X<sup>2</sup>") == "X<sup>2</sup>"
    assert sg._escape("A<br>B") == "A<br>B"
    assert sg._escape("R_p") == "R&#95;p"
    assert sg._escape("<script>x</script>") == "&lt;script&gt;x&lt;/script&gt;"
    # 白名单内侧仍 escape，防 <sub><img></sub>
    assert sg._escape("<sub><img src=x></sub>") == "<sub>&lt;img src=x&gt;</sub>"
    # 带属性的 opening tag 不进白名单
    assert "&lt;sub onclick=x&gt;" in sg._escape("<sub onclick=x>y</sub>")
    # 旧占位符字面 / NUL 不得变成标签
    assert sg._escape("@BR@ literal") == "@BR@ literal"
    assert "<br>" not in sg._escape("@BR@ literal")
    assert sg._escape("a\x00b") == "ab"
    # 白名单内混排：嵌套 <br> 与含换行的下标都要成立
    assert sg._escape("<sub>a<br>b</sub>") == "<sub>a<br>b</sub>"
    assert sg._escape("<sub>a\nb</sub>") == "<sub>a<br>b</sub>"
    # 正文里已写成转义形态的，不被二次还原成标签
    assert sg._escape("&lt;sub&gt;x&lt;/sub&gt;") == "&amp;lt;sub&amp;gt;x&amp;lt;/sub&amp;gt;"
    # highlight 路径同样保留下标
    out = sg.highlight_body("夏普：**R<sub>p</sub>**", "rule")
    assert "R<sub>p</sub>" in out
    assert "<span class=\"hl\">" in out


def test_highlight_body_escapes_and_keeps_highlight():
    out = sg.highlight_body("区间：**0<x<1**", "rule")
    assert "区间：" in out
    assert '<span class="hl">0&lt;x&lt;1</span>' in out
    # 不生成真实 HTML 元素
    assert "<span>" not in out.replace('<span class="hl">', "")


def test_highlight_body_does_not_create_input_element():
    body = "HTML 标签：**<span>** 与 <input>"
    out = sg.highlight_body(body, "rule")
    assert "<input>" not in out
    assert "&lt;input&gt;" in out
    assert "&lt;span&gt;" in out


def test_render_html_escapes_header_sub_zh():
    sc = {
        "kind": "example",
        "header": "a<b",
        "sub": "x & y",
        "body": "**B**",
        "narrate": "n",
        "zh": "1 > 0",
    }
    html = sg.render_html(sc, _cfg())
    assert "a&lt;b" in html
    assert "x &amp; y" in html
    assert "1 &gt; 0" in html
    # 不生成真实 HTML 元素（只允许渲染器自己的 span）
    body = html.split("</head>")[1].split("</body>")[0]
    assert "<b>" not in body
    assert "<input>" not in body


def test_render_html_escape_practice_think_field():
    style = sg.load_style("teaching")
    base = {
        "kind": "practice",
        "header": "h",
        "sub": "s",
        "body": "**?**",
        "narrate": "n",
    }
    # 缺省沿用文案
    assert "先想一想，别急着看答案" in sg.render_html(base, _cfg(style))
    # 自定义文本（含特殊字符按字面显示）
    sc = dict(base, think="a < b & c")
    html = sg.render_html(sc, _cfg(style))
    assert "a &lt; b &amp; c" in html
    assert "先想一想" not in html
    # 空字符串隐藏提示与间距
    sc2 = dict(base, think="")
    html2 = sg.render_html(sc2, _cfg(style))
    assert '<div class="think">' not in html2
    assert "先想一想" not in html2


def test_render_html_no_double_substitution():
    # 内容里含 __SUB__ 等槽位 token：不应被后续槽二次解释，也不被误判为残留占位符
    sc = {
        "kind": "rule",
        "header": "__SUB__",
        "sub": "real",
        "body": "**B**",
        "narrate": "n",
    }
    html = sg.render_html(sc, _cfg())
    assert "&#95;&#95;SUB&#95;&#95;" in html  # header 里的 __SUB__ 被中和，按字面显示
    assert (
        html.count("real") == 1
    )  # sub 槽注入一次，header 里的 __SUB__ 不会被替换成 real
    assert not sg.validate_rendered_html(html, 0)  # 不产生残留占位符错误


# ---- 02 WAV 解码 ----


def test_decode_wav_zero_samples():
    pcm = np.zeros(24000, dtype=np.int16)
    data = wav_bytes(pcm)
    out, rate, ch, sw = mv.decode_wav(data)
    assert rate == 24000 and ch == 1 and sw == 2
    assert len(out) == 24000
    assert not np.any(out)


def test_decode_wav_ignores_extra_chunk():
    pcm = np.arange(1000, dtype=np.int16)
    data = wav_bytes(pcm, extra_list=True)
    out, rate, ch, sw = mv.decode_wav(data)
    assert len(out) == 1000
    assert np.array_equal(out, pcm)


def test_decode_wav_reports_actual_params():
    stereo = wav_bytes(np.zeros(100, dtype=np.int16), channels=2)
    _, rate, ch, sw = mv.decode_wav(stereo)
    assert ch == 2 and sw == 2
    lowrate = wav_bytes(np.zeros(100, dtype=np.int16), rate=16000)
    _, rate2, ch2, sw2 = mv.decode_wav(lowrate)
    assert rate2 == 16000


def test_decode_wav_rejects_non_16bit():
    pcm8 = np.zeros(100, dtype=np.int8)
    data = wav_bytes(pcm8, sampwidth=1)
    with pytest.raises(RuntimeError):
        mv.decode_wav(data)


def test_prepare_scene_audio_keeps_silence():
    # 24k mono 零样本 WAV → decode → prepare 后仍静音
    raw = np.zeros(24000, dtype=np.int16)
    pcm, n_frames, dur, narr = mv.prepare_scene_audio(raw, 0.0, 30)
    assert not np.any(pcm)
    assert narr == 30


# ---- 03 预览溢出（浏览器探针）----


def test_motion_probe_states_static_and_delayed_coverage():
    assert sg._motion_probe_states([{"type": "none", "delay": 0}]) == [(0.0, 1.0)]
    effects = [{"type": "zoom_in", "delay": 2}]
    states = sg._motion_probe_states(effects)
    # 不依赖真实旁白时长：延迟动效的初态与放大末态都必须落在采样状态内
    scales = [sg.motion_vars(effects, e, d)[0] for e, d in states]
    assert min(scales) == 1.0
    assert max(scales) == pytest.approx(1.055)


# ---- 04 hold 冻结 ----


def test_frame_motion_state_matches_seconds_across_fps():
    effects = [{"type": "zoom_in", "delay": 2}]
    # 6 秒旁白：fps=2 → 12 帧，fps=30 → 180 帧；同一秒数状态一致（允许一帧量化）
    for fps, narr in ((2, 12), (30, 180)):
        assert sg.frame_motion_state(effects, 0, fps, narr) == (1.0, 1.0, 0.0)
        at_4s = sg.frame_motion_state(effects, int(4 * fps), fps, narr)
        assert at_4s[0] == pytest.approx(1.048125)
        # hold/尾垫帧（k ≥ narr_frames）冻结在末态
        held = sg.frame_motion_state(effects, narr + fps, fps, narr)
        assert held[0] == pytest.approx(1.055)


def test_frame_motion_state_delay_at_or_after_narration_never_starts():
    # 6 秒旁白、delay 7 秒：全程保持初态
    effects = [{"type": "zoom_in", "delay": 7}]
    for k in range(14):  # 12 帧旁白 + 2 帧 hold
        assert sg.frame_motion_state(effects, k, 2, 12) == (1.0, 1.0, 0.0)
    # delay 恰等于旁白终点：同样不启动
    for k in range(14):
        assert sg.frame_motion_state([{"type": "pulse", "delay": 6}], k, 2, 12) == (
            1.0,
            1.0,
            0.0,
        )


def test_frame_motion_state_single_frame_narration():
    # 零旁白除零保护：narr_frames=1 时不抛错
    state = sg.frame_motion_state([{"type": "zoom_in", "delay": 0}], 0, 30, 1)
    assert state[0] == 1.0


def test_delayed_zoom_starts_after_two_seconds_and_finishes_with_narration():
    effects = sg.resolve_motion({"kind": "rule", "motion": [{"type": "zoom_in", "delay": 2}]})
    assert sg.motion_vars(effects, 1.5, duration_seconds=6) == (1.0, 1.0, 0.0)
    assert sg.motion_vars(effects, 4, duration_seconds=6) == pytest.approx((1.048125, 1.0, 0.0))
    assert sg.motion_vars(effects, 6, duration_seconds=6) == pytest.approx((1.055, 1.0, 0.0))
    assert sg.motion_vars(effects, 9, duration_seconds=6) == pytest.approx((1.055, 1.0, 0.0))


@pytest.mark.parametrize("motion", ["pulse", "zoom_out"])
def test_delayed_motion_has_no_effect_before_start_or_beyond_narration(motion):
    effects = [{"type": motion, "delay": 2}]
    assert sg.motion_vars(effects, 0, duration_seconds=6) == (1.0, 1.0, 0.0)
    assert sg.motion_vars(effects, 1.9, duration_seconds=6) == (1.0, 1.0, 0.0)
    assert sg.motion_vars(effects, 2, duration_seconds=6)[0] > 1
    assert sg.motion_vars(effects, 9, duration_seconds=1) == (1.0, 1.0, 0.0)
    assert sg.motion_vars(effects, 9, duration_seconds=0) == (1.0, 1.0, 0.0)


def test_prepare_scene_audio_reports_narration_frames():
    raw = np.zeros(24000, dtype=np.int16)  # 1s @ 24k
    pcm, n_frames, dur, narr = mv.prepare_scene_audio(raw, 3.0, 30)
    assert narr == 30
    assert n_frames > narr  # hold + 尾垫使总帧数更多
    assert not np.any(pcm)


# ---- 05 fps 校验 ----


@pytest.mark.parametrize("bad", [0, -1, True, 29.5, "30", "abc", 30.0])
def test_validate_storyboard_rejects_invalid_fps(bad):
    tpl = load_sample()
    tpl["fps"] = bad
    errors, _ = sg.validate_storyboard(tpl)
    assert any("fps" in e for e in errors)


def test_validate_storyboard_accepts_default_and_valid_fps():
    tpl = load_sample()
    errors, _ = sg.validate_storyboard(tpl)
    assert not any("fps" in e for e in errors)
    tpl["fps"] = 60
    errors, _ = sg.validate_storyboard(tpl)
    assert not any("fps" in e for e in errors)


def test_validate_storyboard_rejects_non_numeric_hold():
    tpl = load_sample()
    for sc in tpl["scenes"]:
        if sc.get("kind") == "practice":
            sc["hold"] = "五秒"
    errors, _ = sg.validate_storyboard(tpl)
    assert any("有限数字" in e for e in errors)


@pytest.mark.parametrize(
    "narrate",
    [
        "这句话对吗？我想五秒。",  # 想×秒
        "接下来三秒，反观你常用的工具。",  # 量词+秒，无「想」前缀
        "给你三秒钟时间分析背后的机制。",  # 三秒钟
        "数三秒再看答案。",  # 阿拉伯数字外的量词动词
        "我想 5 秒。",  # 数字 + 空格
        "想一想，再看答案。",  # 口播思考动作，句中
        "想一想吧。",  # 句末但带语气词
        "想一下。",
    ],
)
def test_validate_storyboard_rejects_practice_think_aloud_in_narrate(narrate):
    tpl = load_sample()
    for sc in tpl["scenes"]:
        if sc.get("kind") == "practice":
            sc["narrate"] = narrate
    errors, _ = sg.validate_storyboard(tpl)
    assert any("禁止口播思考计时" in e for e in errors), narrate


@pytest.mark.parametrize(
    "narrate",
    [
        "这句话对还是不对？",
        "先想想，漫画可以等，但下周要交的钱不能等？",  # 「想想」不是被禁的计时/口播动作
        "请思考：为什么不直接打七五折？",  # 「思考」不误伤
    ],
)
def test_validate_storyboard_accepts_practice_narrate_without_timing(narrate):
    tpl = load_sample()
    for sc in tpl["scenes"]:
        if sc.get("kind") == "practice":
            sc["narrate"] = narrate
    errors, _ = sg.validate_storyboard(tpl)
    assert not any("禁止口播思考计时" in e for e in errors), narrate


def test_prepare_storyboard_rejects_non_integer_size():
    tpl = load_sample()
    tpl["width"] = "1280px"
    tpl["height"] = 720.5
    prep = sg.prepare_storyboard(tpl)
    assert any("width" in e for e in prep["errors"])
    assert any("height" in e for e in prep["errors"])
    assert prep["cfg"].W == 1280 and prep["cfg"].H == 720


def test_preview_reuse_requires_clean_report_of_this_storyboard():
    """复用准入：报告须存在、属本次分镜、且判据通过（判据由闸门单一表达）。"""
    tpl = load_sample()
    scenes = tpl["scenes"]
    fp = "fp00000000"
    with tempfile.TemporaryDirectory(prefix="pv_") as tmp:
        missing = mv.preview_reuse_errors(tmp, scenes, fp)
        assert missing and "未找到" in missing[0]

        path = mv.ra.preview_report_path(tmp)

        def entry(i, sc, findings=(), ph=()):
            return sg.preview_report_entry(
                i, sg.resolve_kind(sc), {"type": "none"}, f"s{i}.png",
                list(findings), list(ph), fp,
            )

        def write_report(entries):
            with open(path, "w", encoding="utf-8") as f:
                json.dump(entries, f)

        report = [entry(i, sc) for i, sc in enumerate(scenes)]
        write_report(report)
        assert mv.preview_reuse_errors(tmp, scenes, fp) == []

        report[0] = entry(
            0, scenes[0], findings=[{"sel": ".body", "how": "clip", "msg": "溢出"}]
        )
        write_report(report)
        assert any("溢出" in e for e in mv.preview_reuse_errors(tmp, scenes, fp))

        report = [entry(i, sc) for i, sc in enumerate(scenes)]
        report[1] = entry(1, scenes[1], ph=["占位符残留"])
        write_report(report)
        assert any(
            "占位符" in e for e in mv.preview_reuse_errors(tmp, scenes, fp)
        )

        # 页数不符
        write_report([entry(0, scenes[0])])
        assert any(
            "页数" in e for e in mv.preview_reuse_errors(tmp, scenes, fp)
        )

        # 别人的报告（分镜指纹不符）：显式 --preview-dir 也不能绕过
        write_report([entry(i, sc) for i, sc in enumerate(scenes)])
        assert any(
            "指纹不符" in e for e in mv.preview_reuse_errors(tmp, scenes, "other")
        )

        # 条目顺序不符（同一份报告被重排）→ 不可信
        write_report(list(reversed([entry(i, sc) for i, sc in enumerate(scenes)])))
        assert any(
            "顺序不符" in e for e in mv.preview_reuse_errors(tmp, scenes, fp)
        )


def test_make_video_skip_preview_rejected_exits_4_before_tts():
    """--skip-preview 复用被拒要有专属退出码 4（worker 据此归 PREVIEW 阶段），
    并停在配音之前。"""
    if not tc.browser_path():
        pytest.skip("no Chrome/Edge available")
    sb = os.path.join(ROOT, "examples", "what_is_harness.json")
    with tempfile.TemporaryDirectory(prefix="mv_stale_") as tmp:
        r = subprocess.run(
            [
                sys.executable,
                "scripts/make_video.py",
                sb,
                "--skip-preview",
                "--preview-dir",
                tmp,  # 空目录：没有 overflow.json
            ],
            cwd=ROOT,
            capture_output=True,
            text=True,
            encoding="utf-8",
            env=dict(os.environ, PYTHONUTF8="1"),
            timeout=120,
        )
    assert r.returncode == 4, r.stdout + r.stderr
    assert "PREVIEW FAILED" in r.stdout
    assert "生成配音" not in r.stdout  # 停在配音之前


def test_make_video_invalid_fps_does_not_call_tts(monkeypatch):
    tpl = load_sample()
    tpl["fps"] = 0
    with tempfile.NamedTemporaryFile(
        suffix=".json", delete=False, mode="w", encoding="utf-8"
    ) as f:
        json.dump(tpl, f, ensure_ascii=False)
        path = f.name
    try:
        monkeypatch.setattr(sys, "argv", ["make_video.py", path])
        calls = []
        monkeypatch.setattr(mv, "mi_tts", lambda text, voice: calls.append(text) or b"")
        with pytest.raises(SystemExit) as e:
            mv.main()
        assert e.value.code == 2
        assert calls == []  # 非法 fps 在 TTS 前被闸门拒绝
    finally:
        os.remove(path)


# ---- 07 CLI 参数解析 ----


def test_build_parser_valid():
    args = mv.build_parser().parse_args(
        ["x.json", "out.mp4", "--style", "teaching", "--preview"]
    )
    assert args.storyboard == "x.json"
    assert args.output == "out.mp4"
    assert args.style == "teaching"
    assert args.preview is True


def test_build_parser_rejects_unknown_option():
    with pytest.raises(SystemExit):
        mv.build_parser().parse_args(["x.json", "--preveiw"])


def test_build_parser_rejects_missing_style_value():
    with pytest.raises(SystemExit):
        mv.build_parser().parse_args(["x.json", "--style"])


def test_build_parser_rejects_extra_positional():
    with pytest.raises(SystemExit):
        mv.build_parser().parse_args(["x.json", "a.mp4", "b.mp4"])


def test_build_parser_help_exits_zero(capsys):
    with pytest.raises(SystemExit) as e:
        mv.build_parser().parse_args(["--help"])
    assert e.value.code == 0


# ---- 08 think 槽与布局校验 ----


def test_validate_layouts_requires_think_slot():
    errs = sg.validate_layouts()
    assert not any("__THINK__" in e for e in errs)


def test_validate_layouts_rejects_inline_baked_style(monkeypatch):
    """layout HTML 属性烘焙视觉样式应被闸门拦下（应走 style token；见 ea2d727）。

    不依赖 pytest tmp_path fixture（pytest 自带的临时目录清理撞上 Windows
    老 lock 时会 PermissionError），改用 tempfile.mkdtemp() 自己管理。
    """
    tmp = tempfile.mkdtemp(prefix="mv_layout_baked_")
    try:
        for kind, fn in sg.LAYOUT_FILES.items():
            with open(os.path.join(tmp, fn), "w", encoding="utf-8") as f:
                f.write(_minimal_layout(kind))
        # 给 layout-rule.html 加内联 font-size（最常见的回归场景）
        path = os.path.join(tmp, "layout-rule.html")
        with open(path, "a", encoding="utf-8") as f:
            f.write('<div style="font-size:30px">x</div>')
        monkeypatch.setattr(sg, "TEMPLATE_DIR", tmp)
        errs = sg.validate_layouts()
        assert any(
            "HTML 属性 style 烘焙" in e and "layout-rule.html" in e for e in errs
        ), f"expected inline-style rejection, got: {errs}"
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_validate_layouts_allows_margin_padding(monkeypatch):
    """纯布局间距（margin/padding）允许内联，不应误伤。"""
    tmp = tempfile.mkdtemp(prefix="mv_layout_margin_")
    try:
        for kind, fn in sg.LAYOUT_FILES.items():
            with open(os.path.join(tmp, fn), "w", encoding="utf-8") as f:
                f.write(_minimal_layout(kind))
        # 给 layout-title.html 加内联 margin-top（应通过）
        path = os.path.join(tmp, "layout-title.html")
        with open(path, "a", encoding="utf-8") as f:
            f.write('<div style="margin-top:26px">x</div>')
        monkeypatch.setattr(sg, "TEMPLATE_DIR", tmp)
        errs = sg.validate_layouts()
        assert not any("HTML 属性 style 烘焙" in e for e in errs), errs
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_sample_passes_think_and_escape():
    tpl = load_sample()
    errors, warns = sg.validate_storyboard(tpl)
    assert not errors


@pytest.mark.parametrize("wrong_body", [None, "", "   ", 123])
def test_side_example_requires_wrong_body(wrong_body):
    tpl = load_sample()
    sc = next(sc for sc in tpl["scenes"] if sg.resolve_kind(sc) == "example")
    sc["layout_variant"] = "side"
    if wrong_body is not None:
        sc["wrong_body"] = wrong_body
    errors, _ = sg.validate_storyboard(tpl)
    assert any("wrong_body" in error for error in errors)


def test_side_example_accepts_independent_wrong_body():
    tpl = load_sample()
    sc = next(sc for sc in tpl["scenes"] if sg.resolve_kind(sc) == "example")
    sc.update(layout_variant="side", wrong_body="He **reading**.")
    errors, _ = sg.validate_storyboard(tpl)
    assert errors == []


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
    html = sg.render_html(sc, _cfg())
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
    html = sg.render_html(sc, _cfg())
    assert "mc" in html or '<span class="hl">' in html
    assert "步骤说明" in html


def test_formula_layout_has_formula_slots():
    raw = open("templates/layout-rule-formula.html", encoding="utf-8").read()
    assert "__FORMULA_MAIN__" in raw
    assert "__PARTS__" in raw
    assert "__BODY__" not in raw or raw.count("__BODY__") == 0
    errs = sg.validate_layouts()
    assert not any("layout-rule-formula.html" in e for e in errs), errs


# ---- 09 独立闸门（storyboard_gate）：唯一规则源 ----


def test_gate_module_imports_no_heavy_deps():
    """闸门模块必须保持纯 stdlib：不拉 playwright/numpy/imageio_ffmpeg。"""
    code = (
        "import sys, storyboard_gate;"
        "heavy = {'playwright', 'numpy', 'imageio_ffmpeg'} & set(sys.modules);"
        "assert not heavy, f'heavy imports leaked: {heavy}'"
    )
    r = subprocess.run(
        [sys.executable, "-c", code],
        cwd=os.path.join(ROOT, "scripts"),
        capture_output=True,
        text=True,
        encoding="utf-8",
        env=dict(os.environ, PYTHONUTF8="1"),
        timeout=60,
    )
    assert r.returncode == 0, r.stderr


def _write_gate_storyboard(path, **scene_overrides):
    tpl = {
        "title": "Gate",
        "voice": "mimo_default",
        "fps": 2,
        "scenes": [
            {"kind": "rule", "header": "H", "sub": "S", "body": "**B**", "narrate": "N"}
        ],
    }
    tpl["scenes"][0].update(**scene_overrides)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(tpl, f, ensure_ascii=False)
    return tpl


def test_validator_and_renderer_cli_agree_on_gate_failure():
    """同一非法分镜，独立校验与渲染器必须给出同一诊断、同一退出码。"""
    tmp = tempfile.mkdtemp(prefix="mv_gate_cli_")
    path = os.path.join(tmp, "bad_motion.json")
    try:
        _write_gate_storyboard(path, motion="bogus")
        env = dict(os.environ, PYTHONUTF8="1")
        v = subprocess.run(
            [sys.executable, "scripts/validate_storyboard.py", path],
            cwd=ROOT, capture_output=True, text=True, encoding="utf-8",
            env=env, timeout=60,
        )
        r = subprocess.run(
            [sys.executable, "scripts/make_video.py", path, "--reuse-audio"],
            cwd=ROOT, capture_output=True, text=True, encoding="utf-8",
            env=env, timeout=120,
        )
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    assert v.returncode == 2, v.stdout + v.stderr
    assert r.returncode == 2, r.stdout + r.stderr
    assert "未知 motion='bogus'" in v.stdout and "试渲染失败" in v.stdout
    assert "未知 motion='bogus'" in r.stdout and "试渲染失败" in r.stdout
    assert "VALIDATION FAILED" in v.stdout and "VALIDATION FAILED" in r.stdout


def test_prepare_storyboard_resolves_variant_and_fallback():
    tpl = load_sample()
    example = next(sc for sc in tpl["scenes"] if sg.resolve_kind(sc) == "example")
    rule = next(sc for sc in tpl["scenes"] if sg.resolve_kind(sc) == "rule")
    example.update(layout_variant="side", wrong_body="He **reading**.")
    rule["layout_variant"] = "side"
    prep = sg.prepare_storyboard(tpl)
    assert prep["errors"] == []
    assert {e["layout_file"] for e in prep["scenes"] if e["variant"] == "side"} == {
        "layout-example-side.html",
        "layout-rule-side.html",
    }
    rule["layout_variant"] = "nope"  # 未知变体 → 回退默认
    prep2 = sg.prepare_storyboard(tpl)
    assert prep2["errors"] == []
    fallback = next(e for e in prep2["scenes"] if e["variant"] == "nope")
    assert fallback["layout_file"] == "layout-rule.html"
    assert fallback["html"] == sg.render_html(rule, prep2["cfg"])


def test_validate_layouts_checks_existing_variant_slots(monkeypatch):
    """存在的变体文件按 kind 基础槽位 + 变体专属槽位校验；缺失变体文件不报错。"""
    tmp = tempfile.mkdtemp(prefix="mv_gate_variant_")
    try:
        for kind, fn in sg.LAYOUT_FILES.items():
            with open(os.path.join(tmp, fn), "w", encoding="utf-8") as f:
                f.write(_minimal_layout(kind))
        # rule side 变体：基于基础槽位但缺 __ZH__ → 应报缺槽
        with open(os.path.join(tmp, "layout-rule-side.html"), "w", encoding="utf-8") as f:
            f.write(_minimal_layout("rule"))
        monkeypatch.setattr(sg, "TEMPLATE_DIR", tmp)
        errs = sg.validate_layouts()
        assert any("layout-rule-side.html" in e and "__ZH__" in e for e in errs), errs
        # 变体文件补齐后不再报
        with open(os.path.join(tmp, "layout-rule-side.html"), "w", encoding="utf-8") as f:
            f.write(_minimal_layout("rule") + " __ZH__")
        errs2 = sg.validate_layouts()
        assert not any("layout-rule-side.html" in e for e in errs2), errs2
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_load_env_explicit_env_wins_over_dotenv(monkeypatch):
    """load_env 不覆盖显式环境变量；缺 dotenv 包时静默跳过。"""
    pytest.importorskip("dotenv")
    tmp = tempfile.mkdtemp(prefix="mv_gate_env_")
    try:
        with open(os.path.join(tmp, ".env"), "w", encoding="utf-8") as f:
            f.write("MV_GATE_TEST_VAR=from_file\n")
        monkeypatch.setattr(sg, "ROOT", tmp)
        monkeypatch.delenv("MV_GATE_TEST_VAR", raising=False)
        sg.load_env()
        assert os.environ.get("MV_GATE_TEST_VAR") == "from_file"
        monkeypatch.setenv("MV_GATE_TEST_VAR", "explicit")
        sg.load_env()
        assert os.environ.get("MV_GATE_TEST_VAR") == "explicit"
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
        os.environ.pop("MV_GATE_TEST_VAR", None)


# ---- 10 图解取色随皮肤 ----


_CHART_FIXTURE = {
    "preset": "curve",
    "range": {"xmin": 0, "xmax": 5, "ymin": 0, "ymax": 100},
    "curve": {
        "color": "__ACCENT__",
        "points": [{"x": 0, "y": 0}, {"x": 5, "y": 100}],
    },
    "highlights": [{"x": 2, "y": 40, "label": "H", "color": "__WRONG__"}],
}


def _rendered_chart_svg(style_name):
    sc = {"kind": "diagram", "header": "H", "body": "B", "chart": _CHART_FIXTURE}
    html = sg.render_html(sc, _cfg(style_name))
    # 只取图解 SVG 本体：layout CSS 里也注入了同一个 accent，整页断言会假通过
    return html[html.index("<svg") : html.index("</svg>")]


def _curve_stroke(svg):
    return re.search(r"<path d='[^']*' fill='none' stroke='([^']+)'", svg).group(1)


def _point_fill(svg):
    return re.search(r"<circle [^>]*fill='([^']+)'[^>]*class='glow-point'", svg).group(1)


def test_chart_colors_follow_active_skin():
    """图解取色必须走当前皮肤 palette。旧实现按扁平 key 读 style，
    而色值嵌在 palette 下，于是恒落函数里写死的默认色。"""
    light = sg.style_token_map(sg.load_style("classroom"))
    dark = sg.style_token_map(sg.load_style("teaching"))
    assert light["__ACCENT__"] != dark["__ACCENT__"]  # 前提：两皮确实不同色

    svg_light = _rendered_chart_svg("classroom")
    assert _curve_stroke(svg_light) == light["__ACCENT__"]
    assert _point_fill(svg_light) == light["__WRONG__"]

    svg_dark = _rendered_chart_svg("teaching")
    assert _curve_stroke(svg_dark) == dark["__ACCENT__"]
    assert _point_fill(svg_dark) == dark["__WRONG__"]


def test_chart_color_accepts_literal_hex():
    colors = sg.style_token_map(sg.load_style("teaching"))
    svg = sg.resolve_chart(
        {
            "preset": "curve",
            "curve": {
                "color": "#abc123",
                "points": [{"x": 0, "y": 0}, {"x": 1, "y": 1}],
            },
        },
        colors,
    )
    assert _curve_stroke(svg) == "#abc123"


# ---- 10b 图解标签不裁切 ----


def test_chart_highlight_labels_stay_inside_viewbox():
    """贴边点的标签会外推出画布被裁掉（实测 "MU→0 饱和" 右缘 532 > 500）。
    断言用产物自身的 rect x/width，不重述实现里的夹取公式。"""
    chart = {
        "preset": "curve",
        "range": {"xmin": 0, "xmax": 5, "ymin": 0, "ymax": 100},
        "curve": {"points": [{"x": 0, "y": 100}, {"x": 5, "y": 0}]},
        "highlights": [
            {"x": 5, "y": 0, "label": "MU→0 饱和见底"},
            {"x": 0, "y": 100, "label": "起点"},
            {"x": 2.5, "y": 50, "label": "中点"},
        ],
    }
    svg = sg.resolve_chart(chart, sg.style_token_map(sg.load_style("teaching")))
    boxes = [
        (float(m.group(1)), float(m.group(2)))
        for m in re.finditer(r"<rect x='([-\d.]+)' y='[-\d.]+' width='([-\d.]+)'", svg)
    ]
    assert len(boxes) == 3, boxes
    for x, w in boxes:
        assert x >= 0, f"标签左缘 {x} 越出 viewBox"
        assert x + w <= 500, f"标签右缘 {x + w:.1f} 越出 viewBox 500"


def _polyline_samples(svg, step=2.0):
    """展开产物里曲线路径为稠密采样点。只取顶点会漏掉"线段穿角"的情况。"""
    d = re.search(r"<path d='([^']+)'", svg).group(1)
    verts = [(float(a), float(b)) for a, b in re.findall(r"(-?[\d.]+) (-?[\d.]+)", d)]
    out = []
    for (ax, ay), (bx, by) in zip(verts, verts[1:]):
        n = max(1, int(abs(bx - ax) / step))
        out.extend(
            (ax + (bx - ax) * i / n, ay + (by - ay) * i / n) for i in range(n + 1)
        )
    return out or verts


def _label_boxes(svg):
    return [
        (float(m.group(1)), float(m.group(2)), float(m.group(3)), float(m.group(4)))
        for m in re.finditer(
            r"<rect x='([-\d.]+)' y='([-\d.]+)' width='([-\d.]+)' height='([-\d.]+)'",
            svg,
        )
    ]


def test_chart_highlight_labels_do_not_cross_the_curve():
    """charts.py docstring 承诺「标签永不压线，与曲线保持 6px 间隙」。
    用产物自身的 path 与 rect 几何核对，不重述避让公式。
    判定对象是曲线中心线（描边宽 5，中心线不入库时视觉上也留得下）。"""
    chart = {
        "preset": "curve",
        "range": {"xmin": 0, "xmax": 5, "ymin": 0, "ymax": 100},
        "curve": {
            "width": 5,
            "points": [
                {"x": 0, "y": 100},
                {"x": 1, "y": 72},
                {"x": 3, "y": 42},
                {"x": 5, "y": 2},
            ],
        },
        "highlights": [
            {"x": 5, "y": 2, "label": "MU→0 饱和见底"},
            {"x": 0, "y": 100, "label": "起点很高"},
            {"x": 3, "y": 42, "label": "中点"},
        ],
    }
    svg = sg.resolve_chart(chart, sg.style_token_map(sg.load_style("teaching")))
    samples = _polyline_samples(svg)
    boxes = _label_boxes(svg)
    assert len(boxes) == 3 and len(samples) > 40, (boxes, len(samples))
    for rx, ry, rw, rh in boxes:
        crossed = [
            (round(x, 1), round(y, 1))
            for x, y in samples
            if rx <= x <= rx + rw and ry <= y <= ry + rh
        ]
        assert not crossed, f"标签盒 ({rx}, {ry}, {rw}x{rh}) 压住曲线，穿过点 {crossed[:3]}"


def test_chart_fn_presets_and_unknown_falls_back_to_linear():
    """curve.fn 预设表达式推导采样点；未知表达式退回 1 - t。"""
    colors = sg.style_token_map(sg.load_style("teaching"))

    def screen_ys(expr):
        svg = sg.resolve_chart(
            {
                "preset": "curve",
                "range": {"xmin": 0, "xmax": 4, "ymin": 0, "ymax": 100},
                "curve": {"fn": expr, "fn_scale": 100},
            },
            colors,
        )
        d = re.search(r"<path d='([^']+)'", svg).group(1)
        return [float(b) for _, b in re.findall(r"(-?[\d.]+) (-?[\d.]+)", d)]

    log = screen_ys("log")
    assert len(log) == 51  # _CURVE_SAMPLES + 1
    assert log[0] > log[-1]  # 屏幕 y 向下为正：取值递增 → 屏幕 y 递减
    assert all(b <= a for a, b in zip(log, log[1:]))  # 单调，不回摆
    assert screen_ys("no-such-fn") == screen_ys("1 - t")  # 未知表达式兜底


# ---- 11 公式页分步动效时间线 ----


def test_formula_motion_vars_timeline_phases():
    parts = [{"id": "num"}, {"id": "den"}]
    # 入场中点（0–15%）：卡抬起中，分式线未开始，无激活项
    # ease_out_cubic(0.5)=0.875 → 抬起已到 7/8，明显快于线性的一半
    v0 = sg.formula_motion_vars(parts, 0.075, 1.0)
    assert v0["active_part"] == ""
    assert v0["card_elev"] == pytest.approx(0.875)
    assert v0["card_y"] == pytest.approx(1.0)
    assert v0["frac_bar"] == 0
    # 主式区（15–40%）：卡已落位，分式线匀速描画（刻意不缓动 → 笔画等速）
    v1 = sg.formula_motion_vars(parts, 0.25, 1.0)
    assert v1["active_part"] == "__main__"
    assert v1["card_y"] == 0
    assert v1["frac_bar"] == pytest.approx(0.4)
    # parts 区均分剩余（每项 30%）：0.40–0.70 → 第一项
    v2 = sg.formula_motion_vars(parts, 0.50, 1.0)
    assert v2["active_part"] == "num"
    assert v2["frac_bar"] == 1.0
    # 0.70–1.00 → 第二项
    v3 = sg.formula_motion_vars(parts, 0.85, 1.0)
    assert v3["active_part"] == "den"
    # hold/尾垫（elapsed ≥ duration）冻在末态
    v4 = sg.formula_motion_vars(parts, 2.0, 1.0)
    assert v4["active_part"] == "den"
    assert v4["card_y"] == 0


def test_formula_motion_vars_zero_duration():
    v = sg.formula_motion_vars([{"id": "a"}, {"id": "b"}], 0.0, 0.0)
    assert v["active_part"] == ""
    assert v["card_y"] == 8


def _matrix(css_transform):
    """'matrix(a, b, c, d, tx, ty)' → 六个浮点数。"""
    return [float(x) for x in css_transform[css_transform.index("(") + 1 : -1].split(",")]


def _formula_sc(**over):
    sc = {
        "kind": "rule", "layout_variant": "formula", "header": "H", "sub": "s",
        "body": "B", "narrate": "N",
        "formula": {
            "num": "A", "den": "B",
            "parts": [
                {"id": "num", "label": "1", "text": "t1"},
                {"id": "den", "label": "2", "text": "t2"},
            ],
        },
    }
    sc.update(over)
    return sc


def test_formula_parts_for_motion_only_on_rule_formula_with_parts():
    sc = _formula_sc()
    assert sg.formula_parts_for_motion(sc) == sc["formula"]["parts"]
    # 非 formula 变体 / 非 rule 页 / 无 formula / parts 缺失或为空 → 不叠加
    assert sg.formula_parts_for_motion(_formula_sc(layout_variant="side")) is None
    assert sg.formula_parts_for_motion(_formula_sc(kind="example")) is None
    assert sg.formula_parts_for_motion(_formula_sc(formula="R = A/B")) is None
    no_parts = _formula_sc()
    del no_parts["formula"]["parts"]
    assert sg.formula_parts_for_motion(no_parts) is None
    assert sg.formula_parts_for_motion(_formula_sc(formula={"num": "A", "den": "B", "parts": []})) is None
    # 普通 rule 页（根本没走变体）同样为 None
    assert sg.formula_parts_for_motion({"kind": "rule", "body": "x"}) is None


def test_formula_motion_css_hooks_present():
    for token in ("--m-card-y", "--m-card-elev", "--m-frac-bar", "--m-part-on", "--m-formula-hl"):
        assert token in sg.MOTION_CSS, token
    assert ".formula-card" in sg.MOTION_CSS
    assert ".formula-bar" in sg.MOTION_CSS
    assert ".step[data-part-id]" in sg.MOTION_CSS
    assert "[data-formula-main]" in sg.MOTION_CSS
    # 钩子只服务 formula 页：其它 layout 不引入这些类名，避免误伤
    raw = open(
        os.path.join(sg.TEMPLATE_DIR, "layout-rule-formula.html"), encoding="utf-8"
    ).read()
    assert "formula-card" in raw and "formula-bar" in raw


def test_browser_formula_vars_drive_computed_style(browser):
    sc = _formula_sc()
    parts = sc["formula"]["parts"]
    page = browser.new_page(viewport={"width": 1280, "height": 720})
    try:
        page.set_content(sg.render_html(sc, _cfg()))

        def snapshot(elapsed):
            sg.apply_motion_css_vars(
                page, sg.MotionState(1.0, 1.0, 0.0),
                sg.formula_motion_vars(parts, elapsed, 1.0),
            )
            return {
                "card": _matrix(page.locator(".formula-card").evaluate(
                    "el => getComputedStyle(el).transform")),
                "bar": _matrix(page.locator(".formula-bar").evaluate(
                    "el => getComputedStyle(el).transform")),
                "steps": page.locator(".step[data-part-id]").evaluate_all(
                    "els => els.map(e => parseFloat(getComputedStyle(e).opacity))"),
                "main": _matrix(page.locator("[data-formula-main]").evaluate(
                    "el => getComputedStyle(el).transform")),
            }

        # 入场中（u=0.05）：卡未落位、分式线宽度 0、parts 全暗、主式不放大
        e = snapshot(0.05)
        assert e["card"][5] == pytest.approx(8 * (1 - sg.ease_out_cubic(1 / 3)), abs=0.01)
        assert e["bar"][0] == pytest.approx(0.0, abs=1e-6)
        assert e["steps"] == [pytest.approx(0.45)] * 2
        assert e["main"][0] == pytest.approx(1.0)
        # 第一个 part 点亮（u=0.50）：卡落位、分式线满宽、仅 num 亮、parts 阶段主式不放大
        p = snapshot(0.50)
        assert p["card"][5] == pytest.approx(0.0, abs=1e-6)
        assert p["bar"][0] == pytest.approx(1.0)
        assert p["steps"] == [pytest.approx(1.0), pytest.approx(0.45)]
        assert p["main"][0] == pytest.approx(1.0)
        # 第二个 part 点亮（u=0.90）：讲过的 num 停在半亮，不再退回全暗
        d = snapshot(0.90)
        assert d["steps"] == [pytest.approx(0.725), pytest.approx(1.0)]
        # 主式阶段（u=0.25）：主式放大一档，parts 仍全暗
        m = snapshot(0.25)
        assert m["main"][0] > 1.0
        assert m["steps"] == [pytest.approx(0.45)] * 2
        # 交回非公式页语义（formula=None）：一切回到末态，不留残值
        sg.apply_motion_css_vars(page, sg.MotionState(1.0, 1.0, 0.0))
        reset = page.locator(".step[data-part-id]").evaluate_all(
            "els => els.map(e => parseFloat(getComputedStyle(e).opacity))"
        )
        assert reset == [pytest.approx(1.0)] * 2
    finally:
        page.close()


# ---- 浏览器实测：文本保真 + 溢出探测（找不到浏览器则跳过）----


@pytest.fixture(scope="session")
def browser():
    path = tc.browser_path()
    if not path:
        pytest.skip("no Chrome/Edge available")
    from playwright.sync_api import sync_playwright

    with sync_playwright() as p:
        b = p.chromium.launch(executable_path=path, headless=True)
        yield b
        b.close()


def test_browser_text_fidelity(browser):
    sc = {
        "kind": "rule",
        "header": "区间",
        "sub": "",
        "body": "区间：**0<x<1**",
        "narrate": "n",
    }
    page = browser.new_page(viewport={"width": 1280, "height": 720})
    page.set_content(sg.render_html(sc, _cfg()))
    assert page.locator(".body").inner_text().strip() == "区间：0<x<1"
    page.close()


def test_browser_no_input_element_from_content(browser):
    sc = {
        "kind": "rule",
        "header": "h",
        "sub": "",
        "body": "HTML 标签：**<span>** 与 <input>",
        "narrate": "n",
    }
    page = browser.new_page(viewport={"width": 1280, "height": 720})
    page.set_content(sg.render_html(sc, _cfg()))
    assert page.locator("input").count() == 0
    assert page.locator("span.hl").count() == 1
    page.close()


def test_browser_overflow_detects_hl_scale(browser):
    # 复现 issue 03 的核心：.hl 独立变换（放大）时即使容器 .body 布局不变也会被测量到
    sc = {
        "kind": "rule",
        "header": "h",
        "sub": "",
        "body": "**" + "知识点" * 22 + "**",
        "narrate": "n",
    }
    page = browser.new_page(viewport={"width": 1280, "height": 720})
    page.set_content(sg.render_html(sc, _cfg()))
    # 放大高亮词（模拟动效对 .hl 的独立缩放），.stage/.body 布局不变
    sg.apply_motion_css_vars(page, sg.MotionState(1.0, 3.0, 0.0))
    findings = sg.preview_overflow(page, 1280, 720, kind="rule")
    sels = [f["sel"] for f in findings]
    assert ".hl" in sels
    assert ".body" not in sels  # 容器未溢出，只有被放大的高亮词被报告
    page.close()


def test_browser_overflow_detects_delayed_zoom_end_state(browser):
    # 延迟动效（delay=2）没有真实旁白时长：预览探测的可达状态里必须含放大末态，
    # 且末态的溢出能被探测（初态同内容不溢出）——不依赖旁白秒数。
    sc = {
        "kind": "rule",
        "header": "h",
        "sub": "s",
        "body": "**B**",
        "narrate": "n",
        "motion": [{"type": "zoom_in", "delay": 2}],
    }
    page = browser.new_page(viewport={"width": 1280, "height": 720})
    try:
        page.set_content(sg.render_html(sc, _cfg()))
        motion = sg.resolve_motion(sc, True)
        end_state = max(
            sg._motion_probe_states(motion),
            key=lambda s: sg.motion_vars(motion, *s)[0],
        )
        sg.apply_motion_css_vars(page, sg.motion_vars(motion, 0.0, 1.0))
        right_initial = page.evaluate(
            "document.querySelector('.body').getBoundingClientRect().right"
        )
        sg.apply_motion_css_vars(page, sg.motion_vars(motion, *end_state))
        right_end = page.evaluate(
            "document.querySelector('.body').getBoundingClientRect().right"
        )
        assert right_end > right_initial
        width = (right_initial + right_end) / 2  # 初态不越界、末态越界的探测宽度

        sg.apply_motion_css_vars(page, sg.motion_vars(motion, 0.0, 1.0))
        sels_initial = [
            f["sel"] for f in sg.preview_overflow(page, width, 720, kind="rule")
        ]
        assert ".body" not in sels_initial
        sg.apply_motion_css_vars(page, sg.motion_vars(motion, *end_state))
        sels_end = [
            f["sel"] for f in sg.preview_overflow(page, width, 720, kind="rule")
        ]
        assert ".body" in sels_end
    finally:
        page.close()


def test_browser_overflow_reports_clipped_text(browser):
    # 盒子仍在视口内，但槽自身 overflow:hidden 把字裁掉，也要报
    sc = {"kind": "rule", "header": "h", "sub": "s", "body": "完整的一句话", "narrate": "n"}
    page = browser.new_page(viewport={"width": 1280, "height": 720})
    page.set_content(sg.render_html(sc, _cfg()))
    page.evaluate(
        """() => {
          const b = document.querySelector('.body');
          b.style.display = 'block';
          b.style.overflow = 'hidden';
          b.style.height = '20px';
          b.style.width = '80px';
          b.textContent = '这是一段明显超出卡片高度和宽度的说明文字';
        }"""
    )
    findings = sg.preview_overflow(page, 1280, 720, kind="rule")
    assert any(f["sel"] == ".body" and "裁切" in f["msg"] for f in findings)
    page.close()


def test_browser_overflow_reports_top_bound(browser):
    # 四侧边界：顶部裁切也要被报告
    sc = {"kind": "rule", "header": "h", "sub": "s", "body": "**B**", "narrate": "n"}
    page = browser.new_page(viewport={"width": 1280, "height": 720})
    page.set_content(sg.render_html(sc, _cfg()))
    page.evaluate(
        "() => { const t = document.querySelector('.title'); t.style.position = 'absolute'; t.style.top = '-100px'; }"
    )
    findings = sg.preview_overflow(page, 1280, 720, kind="rule")
    assert any(f["sel"] == ".title" for f in findings)
    page.close()


def test_browser_side_example_has_distinct_escaped_columns(browser):
    sc = {
        "kind": "example",
        "layout_variant": "side",
        "header": "Compare",
        "body": "He **is reading**.",
        "wrong_body": "He **reading**.<br><input>",
        "narrate": "Compare the sentences.",
    }
    page = browser.new_page(viewport={"width": 1280, "height": 720})
    try:
        html = sg.render_html(sc, _cfg())
        assert sg.validate_rendered_html(html, 0) == []
        page.set_content(html)
        assert page.locator(".col-correct .col-text").inner_text() == "He is reading."
        assert (
            page.locator(".col-wrong .col-text").inner_text() == "He reading.\n<input>"
        )
        assert page.locator(".col-correct .hl").inner_text() == "is reading"
        assert page.locator(".col-wrong .err").inner_text() == "reading"
        assert page.locator("input").count() == 0
    finally:
        page.close()


@pytest.mark.parametrize(
    "motion_enabled,scene_motion",
    [
        (False, "focus"),
        (True, "none"),
        (True, [{"type": "none", "delay": 0}]),
    ],
)
def test_browser_static_diagram_first_frame_is_complete(
    browser, motion_enabled, scene_motion
):
    sc = {
        "kind": "diagram",
        "header": "Diagram",
        "body": "B",
        "chart": {"preset": "curve", "highlights": [{"x": 1, "y": 50, "label": "A"}]},
        "motion": scene_motion,
    }
    page = browser.new_page(viewport={"width": 1280, "height": 720})
    try:
        page.set_content(
            sg.render_html(sc, _cfg(motion=motion_enabled))
        )
        page.screenshot(type="png")
        states = page.locator(".stagger-item,.glow-point").evaluate_all(
            "els => els.map(el => [getComputedStyle(el).opacity, getComputedStyle(el).transform])"
        )
        assert states and all(state == ["1", "none"] for state in states)
        assert page.evaluate("document.getAnimations().length") == 0
        offsets = page.locator(".draw-path").evaluate_all(
            "els => els.map(el => parseFloat(getComputedStyle(el).strokeDashoffset))"
        )
        assert all(offset == 0 for offset in offsets)
    finally:
        page.close()


def test_browser_animated_diagram_still_has_animations(browser):
    sc = {
        "kind": "diagram",
        "header": "Diagram",
        "body": "B",
        "chart": {"preset": "curve", "highlights": [{"x": 2, "y": 40, "label": "B"}]},
    }
    page = browser.new_page(viewport={"width": 1280, "height": 720})
    try:
        page.set_content(sg.render_html(sc, _cfg()))
        assert page.evaluate("document.getAnimations().length") > 0
    finally:
        page.close()


def _write_preview_storyboard(tmp, name, scene):
    """run_preview 会读分镜文件算指纹，故给它一个真实存在的分镜（生产路径必有）。"""
    path = os.path.join(tmp, name)
    with open(path, "w", encoding="utf-8") as f:
        json.dump({"scenes": [scene]}, f, ensure_ascii=False)
    return path


def test_preview_rejects_clipped_formula():
    sc = {
        "kind": "rule", "layout_variant": "formula", "header": "Formula",
        "body": "<br>".join(["A = B + C"] * 24), "narrate": "Formula",
    }
    # run_preview owns its Playwright loop; keep it separate from the browser fixture.
    with tempfile.TemporaryDirectory(prefix="mv_formula_overflow_") as tmp, ThreadPoolExecutor(max_workers=1) as executor:
        sb = _write_preview_storyboard(tmp, "formula.json", sc)
        result = executor.submit(
            mv.run_preview, sb, _cfg(motion=False), [sc],
            tc.browser_path(), preview_dir=os.path.join(tmp, "preview"),
        ).result()
    assert result == 1


@pytest.mark.parametrize("kind,variant,field", [
    ("rule", "formula", "zh"),
    ("rule", "side", "zh"),
    ("example", "side", "body"),
    ("example", "side", "wrong_body"),
])
def test_preview_rejects_clipped_variant_content(kind, variant, field):
    sc = {
        "kind": kind, "layout_variant": variant, "header": "Compare",
        "body": "A", "wrong_body": "B", "zh": "Detail", "narrate": "Compare",
        field: "<br>".join(["A = B + C"] * 24),
    }
    with tempfile.TemporaryDirectory(prefix="mv_variant_overflow_") as tmp, ThreadPoolExecutor(max_workers=1) as executor:
        sb = _write_preview_storyboard(tmp, "variant.json", sc)
        result = executor.submit(
            mv.run_preview, sb, _cfg(motion=False), [sc],
            tc.browser_path(), preview_dir=os.path.join(tmp, "preview"),
        ).result()
    assert result == 1


# ---- 溢出选择器表与判据（S3/S4 清理）----


def test_overflow_selectors_unique_and_clip_exempt():
    """同一 DOM 元素不能在表里出现两次；装饰性容器不计入裁切。"""
    rule = sg._OVERFLOW_SELECTORS_BY_KIND["rule"]
    assert len(rule) == len(set(rule))
    # .step-text 与 .part-text 是同一个元素（build_formula_parts_html），只留一个
    assert ".step-text" in rule and ".part-text" not in rule
    diagram = sg._OVERFLOW_SELECTORS_BY_KIND["diagram"]
    # 视口越界仍要报，但圆角裁切不算文字丢失
    assert ".chart-container" in diagram
    assert ".chart-container" in sg._CLIP_EXEMPT_SELECTORS
    assert not (sg._CLIP_EXEMPT_SELECTORS & set(rule))


def test_finding_key_separates_viewport_and_clip():
    """同一槽同一文本的「越界」与「裁切」是两条诊断，去重键必须区分；
    坐标不入键，否则动效各状态会重复上报。"""
    v = {"sel": ".body", "how": "viewport", "txt": "同一段字", "msg": "…"}
    c = {"sel": ".body", "how": "clip", "txt": "同一段字", "msg": "…"}
    assert mv._finding_key(v) != mv._finding_key(c)
    # 坐标（或整段文案）变化不改变键：动效各状态坐标会变
    v2 = {"sel": ".body", "how": "viewport", "txt": "同一段字",
          "msg": "完全换一段文案 left=99 top=9"}
    assert mv._finding_key(v) == mv._finding_key(v2)
    # 元素文本变化 → 不同键
    assert mv._finding_key(dict(v, txt="别的字")) != mv._finding_key(v)


def test_finding_key_is_built_from_producer_fields(browser):
    """去重键取自 preview_overflow 的字段，不解析它的人读消息。

    先前的测试手写诊断字符串，等于验证了一个自己臆造的格式；这里喂真实产出，
    并断言改写文案不改变键。
    """
    sc = {"kind": "rule", "header": "h", "sub": "s", "body": "完整的一句话", "narrate": "n"}
    page = browser.new_page(viewport={"width": 1280, "height": 720})
    try:
        page.set_content(sg.render_html(sc, _cfg()))
        page.evaluate(
            """() => {
              const b = document.querySelector('.body');
              b.style.overflow = 'hidden';
              b.style.height = '20px';
              b.textContent = '这是一段明显超出卡片高度的说明文字';
            }"""
        )
        findings = sg.preview_overflow(page, 1280, 720, kind="rule")
    finally:
        page.close()
    assert findings, "应至少报一条裁切"
    f = findings[0]
    assert "txt" in f and f["txt"], "生产方必须给出 txt 字段"
    key = mv._finding_key(f)
    assert mv._finding_key(dict(f, msg="换一段诊断文案")) == key
    assert mv._finding_key(dict(f, txt="另一个元素文本")) != key


def test_browser_clipped_formula_part_reported_once(browser):
    """公式部件被裁切只报一条（.step-text/.part-text 不再重复命中）。"""
    sc = {
        "kind": "rule", "layout_variant": "formula", "header": "h", "narrate": "n",
        "formula": {"display": "A", "parts": [{"label": "1", "text": "部件说明"}]},
    }
    page = browser.new_page(viewport={"width": 1280, "height": 720})
    try:
        page.set_content(sg.render_html(sc, _cfg()))
        assert page.evaluate("document.querySelectorAll('.step-text').length") == 1
        page.evaluate(
            """() => {
              const el = document.querySelector('.step-text');
              el.style.overflow = 'hidden';
              el.style.height = '12px';
              el.textContent = '明显超出部件高度的说明文字，用来触发裁切检测';
            }"""
        )
        findings = sg.preview_overflow(page, 1280, 720, kind="rule")
    finally:
        page.close()
    hits = [f for f in findings if f["sel"] in (".step-text", ".part-text")]
    assert len(hits) == 1, hits
    assert hits[0]["how"] == "clip"


def test_browser_chart_container_clip_exempt_but_viewport_reported(browser):
    """.chart-container 的圆角裁切不报；越出视口仍报（豁免只针对裁切）。"""
    sc = {
        "kind": "diagram", "header": "D", "body": "B",
        "chart": {"preset": "curve", "highlights": [{"x": 2, "y": 40, "label": "B"}]},
    }
    page = browser.new_page(viewport={"width": 1280, "height": 720})
    try:
        page.set_content(sg.render_html(sc, _cfg()))
        page.evaluate(
            """() => {
              const el = document.querySelector('.chart-container');
              el.style.overflow = 'hidden';
              el.style.height = '10px';
            }"""
        )
        clipped = [
            f for f in sg.preview_overflow(page, 1280, 720, kind="diagram")
            if f["sel"] == ".chart-container"
        ]
        page.evaluate(
            """() => {
              const el = document.querySelector('.chart-container');
              el.style.height = '';
              el.style.position = 'fixed';
              el.style.left = '-400px';
            }"""
        )
        moved = [
            f for f in sg.preview_overflow(page, 1280, 720, kind="diagram")
            if f["sel"] == ".chart-container"
        ]
    finally:
        page.close()
    assert clipped == []
    assert [f["how"] for f in moved] == ["viewport"]


# ---- 闸门解析器协议（S4-9/10、S5-17/18）----


def _practice_scene(tpl):
    return next(sc for sc in tpl["scenes"] if sc.get("kind") == "practice")


@pytest.mark.parametrize("bad", [None, "", "五秒", -1, float("nan"), float("inf")])
def test_gate_rejects_explicit_null_and_negative_hold(bad):
    """显式 null / 空串 / 负数与「缺省」不同待遇：同一类输入不能两种待遇。"""
    tpl = load_sample()
    _practice_scene(tpl)["hold"] = bad
    errors, _ = sg.validate_storyboard(tpl)
    assert any("hold" in e for e in errors), bad


def test_gate_accepts_numeric_string_hold():
    tpl = load_sample()
    _practice_scene(tpl)["hold"] = "5"
    errors, _ = sg.validate_storyboard(tpl)
    assert not any("hold" in e for e in errors)


def test_gate_reports_hold_error_once():
    """非法 hold 只报一条：不再叠一条下限错误（相邻两个 practice 分支已合并）。"""
    tpl = load_sample()
    _practice_scene(tpl)["hold"] = "五秒"
    errors, _ = sg.validate_storyboard(tpl)
    assert len([e for e in errors if "hold" in e]) == 1


def test_gate_hold_floor_message_matches_docs():
    """报错文案与 docs/teaching-method.md 的 `hold>=5.0` 字面一致。"""
    tpl = load_sample()
    _practice_scene(tpl)["hold"] = 1.0
    errors, _ = sg.validate_storyboard(tpl)
    assert any("hold>=5.0" in e for e in errors)


def test_gate_fps_uses_shared_positive_int_rule():
    """fps 与宽高共用同一判据与文案（不再各写一套）。"""
    tpl = load_sample()
    tpl["fps"] = "30"
    errors, _ = sg.validate_storyboard(tpl)
    assert "fps 须为正整数（当前 '30'）；缺省 30" in errors


def test_gate_rejects_explicit_null_size():
    tpl = load_sample()
    tpl["width"] = None
    prep = sg.prepare_storyboard(tpl)
    assert any("width" in e for e in prep["errors"])
    assert prep["cfg"].W == 1280


# ---- 皮肤名解析：三个入口共用一条规则 ----


def test_resolve_style_name_precedence():
    assert sg.resolve_style_name({"style": "classroom"}, "explainer") == "explainer"
    assert sg.resolve_style_name({"style": "classroom"}) == "classroom"
    assert sg.resolve_style_name({}) == "teaching"
    assert sg.resolve_style_name(None) == "teaching"


def test_style_name_rule_is_written_once():
    """两个 CLI 必须委托 resolve_style_name，不得自己再拼一遍。

    各自拼一遍时，一旦分歧就表现为验收报「本次运行没有 manifest」——
    看起来像没渲染，其实是默认皮肤不一致。
    """
    for rel in ("render_worker.py", "worker_verify.py"):
        src = open(os.path.join(ROOT, "scripts", rel), encoding="utf-8").read()
        assert 'get("style"' not in src, f"{rel} 又自己拼了一遍皮肤名规则"
        assert "resolve_style_name" in src, f"{rel} 未委托 resolve_style_name"


def test_style_name_agrees_with_prepare_storyboard():
    """CLI 侧与 prepare_storyboard 侧对同一分镜得到同一个皮肤名。"""
    tpl = load_sample()
    tpl["style"] = "classroom"
    prep = sg.prepare_storyboard(tpl)
    assert prep["cfg"].style_name == "classroom"
    assert sg.resolve_style_name(tpl) == prep["cfg"].style_name
    assert sg.resolve_style_name(tpl, "explainer") == "explainer"
